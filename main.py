"""
多交易所辅助工具 — FastAPI backend
Supports: Binance, OKX, Bybit, Gate.io, KuCoin
Features: 下单, 提币, 借币, 循环借币
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import ccxt
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── Config ────────────────────────────────────────────────────────────────────

CONFIG_FILE = "config.json"
SUPPORTED = ["binance", "okx", "bybit", "gate", "kucoin"]


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"exchanges": {}}


def save_config(config: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


# ── Exchange factory ──────────────────────────────────────────────────────────

def make_exchange(eid: str) -> ccxt.Exchange:
    config = load_config()
    creds = config.get("exchanges", {}).get(eid)
    if not creds:
        raise HTTPException(404, f"交易所 '{eid}' 未配置，请先在设置中添加 API Key")
    cls = getattr(ccxt, eid, None)
    if cls is None:
        raise HTTPException(400, f"不支持的交易所: {eid}")
    return cls(
        {
            "apiKey": creds.get("api_key", ""),
            "secret": creds.get("secret", ""),
            "password": creds.get("password", ""),  # OKX / KuCoin passphrase
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        }
    )


# ── Pydantic models ───────────────────────────────────────────────────────────

class ExchangeCreds(BaseModel):
    api_key: str
    secret: str
    password: str = ""


class OrderReq(BaseModel):
    exchange: str
    symbol: str          # e.g. "BTC/USDT"
    type: str            # "market" | "limit"
    side: str            # "buy" | "sell"
    amount: float
    price: Optional[float] = None
    params: Dict[str, Any] = {}


class WithdrawReq(BaseModel):
    exchange: str
    coin: str
    amount: float
    address: str
    tag: Optional[str] = None
    network: Optional[str] = None


class BorrowReq(BaseModel):
    exchange: str
    coin: str
    amount: float
    mode: str = "cross"          # "cross" | "isolated"
    symbol: Optional[str] = None # required for isolated


class RepayReq(BaseModel):
    exchange: str
    coin: str
    amount: float
    mode: str = "cross"
    symbol: Optional[str] = None


class TransferReq(BaseModel):
    exchange: str
    coin: str
    amount: float
    from_account: str   # "spot" | "margin" | "futures" | "funding"
    to_account: str


class LoopReq(BaseModel):
    exchange: str
    collateral: str       # coin already held as collateral, e.g. "USDT"
    borrow_coin: str      # coin to borrow, e.g. "USDT" or "BTC"
    initial: float        # base collateral amount to derive borrow sizes from
    ratio: float = 0.8    # fraction of previous amount to borrow each loop
    loops: int = 5        # number of iterations
    mode: str = "cross"
    symbol: Optional[str] = None


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="多交易所辅助工具", version="1.0.0")
app.mount("/static", StaticFiles(directory="static"), name="static")

TASKS: Dict[str, dict] = {}  # in-memory task store


@app.get("/", response_class=HTMLResponse)
async def root() -> str:
    with open("static/index.html", encoding="utf-8") as f:
        return f.read()


# ── Exchange management ───────────────────────────────────────────────────────

@app.get("/api/exchanges")
async def list_exchanges():
    config = load_config()
    return {
        "supported": SUPPORTED,
        "configured": list(config.get("exchanges", {}).keys()),
    }


@app.post("/api/exchanges/{eid}")
async def save_exchange(eid: str, creds: ExchangeCreds):
    if eid not in SUPPORTED:
        raise HTTPException(400, f"不支持的交易所: {eid}")
    config = load_config()
    config.setdefault("exchanges", {})[eid] = creds.model_dump()
    save_config(config)
    return {"ok": True}


@app.delete("/api/exchanges/{eid}")
async def del_exchange(eid: str):
    config = load_config()
    config.get("exchanges", {}).pop(eid, None)
    save_config(config)
    return {"ok": True}


# ── Balances ──────────────────────────────────────────────────────────────────

@app.get("/api/balances/{eid}")
async def get_balances(eid: str, type: str = "spot"):
    ex = make_exchange(eid)
    try:
        params: dict = {}
        if type == "margin":
            if eid == "binance":
                params = {"type": "margin"}
            elif eid == "okx":
                params = {"type": "trading"}
            elif eid == "bybit":
                params = {"accountType": "UNIFIED"}
        bal = ex.fetch_balance(params)
        nonzero = {k: v for k, v in bal["total"].items() if v and float(v) > 0}
        return {"exchange": eid, "type": type, "balances": nonzero}
    except Exception as e:
        raise HTTPException(400, str(e))


# ── Orders ────────────────────────────────────────────────────────────────────

@app.post("/api/orders")
async def create_order(req: OrderReq):
    ex = make_exchange(req.exchange)
    try:
        result = ex.create_order(
            req.symbol, req.type, req.side, req.amount, req.price, req.params
        )
        return {"ok": True, "order": result}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/orders/{eid}")
async def open_orders(eid: str, symbol: Optional[str] = None):
    ex = make_exchange(eid)
    try:
        return {"orders": ex.fetch_open_orders(symbol)}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.delete("/api/orders/{eid}/{order_id}")
async def cancel_order(eid: str, order_id: str, symbol: str = Query(...)):
    ex = make_exchange(eid)
    try:
        return {"ok": True, "result": ex.cancel_order(order_id, symbol)}
    except Exception as e:
        raise HTTPException(400, str(e))


# ── Withdraw ──────────────────────────────────────────────────────────────────

@app.post("/api/withdraw")
async def withdraw(req: WithdrawReq):
    ex = make_exchange(req.exchange)
    try:
        params = {}
        if req.network:
            params["network"] = req.network
        result = ex.withdraw(req.coin, req.amount, req.address, req.tag, params)
        return {"ok": True, "result": result}
    except Exception as e:
        raise HTTPException(400, str(e))


# ── Transfer between accounts ─────────────────────────────────────────────────

@app.post("/api/transfer")
async def transfer(req: TransferReq):
    ex = make_exchange(req.exchange)
    try:
        result = ex.transfer(req.coin, req.amount, req.from_account, req.to_account)
        return {"ok": True, "result": result}
    except Exception as e:
        raise HTTPException(400, str(e))


# ── Margin borrow / repay helpers ─────────────────────────────────────────────

def _do_borrow(
    ex: ccxt.Exchange, coin: str, amount: float, mode: str, symbol: Optional[str]
) -> dict:
    # Try ccxt unified method first
    try:
        if mode == "cross":
            return ex.borrow_margin(coin, amount, None, {})
        else:
            return ex.borrow_margin(coin, amount, symbol, {})
    except (AttributeError, ccxt.NotSupported):
        pass

    eid = ex.id
    if eid == "binance":
        p: dict = {"asset": coin, "amount": amount}
        if mode == "isolated" and symbol:
            p.update({"isIsolated": "TRUE", "symbol": symbol.replace("/", "")})
        return ex.sapi_post_margin_loan(p)
    if eid == "okx":
        return ex.private_post_account_borrow_repay(
            {"ccy": coin, "side": "borrow", "amt": str(amount)}
        )
    if eid == "bybit":
        return ex.private_post_v5_account_borrow(
            {"currency": coin, "qty": str(amount)}
        )
    raise HTTPException(400, f"{eid} 暂不支持借币操作")


def _do_repay(
    ex: ccxt.Exchange, coin: str, amount: float, mode: str, symbol: Optional[str]
) -> dict:
    try:
        if mode == "cross":
            return ex.repay_margin(coin, amount, None, {})
        else:
            return ex.repay_margin(coin, amount, symbol, {})
    except (AttributeError, ccxt.NotSupported):
        pass

    eid = ex.id
    if eid == "binance":
        p: dict = {"asset": coin, "amount": amount}
        if mode == "isolated" and symbol:
            p.update({"isIsolated": "TRUE", "symbol": symbol.replace("/", "")})
        return ex.sapi_post_margin_repay(p)
    if eid == "okx":
        return ex.private_post_account_borrow_repay(
            {"ccy": coin, "side": "repay", "amt": str(amount)}
        )
    if eid == "bybit":
        return ex.private_post_v5_account_repay(
            {"currency": coin, "qty": str(amount)}
        )
    raise HTTPException(400, f"{eid} 暂不支持还款操作")


@app.post("/api/borrow")
async def borrow(req: BorrowReq):
    ex = make_exchange(req.exchange)
    try:
        result = _do_borrow(ex, req.coin, req.amount, req.mode, req.symbol)
        return {"ok": True, "result": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/repay")
async def repay(req: RepayReq):
    ex = make_exchange(req.exchange)
    try:
        result = _do_repay(ex, req.coin, req.amount, req.mode, req.symbol)
        return {"ok": True, "result": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, str(e))


# ── Loop borrow ───────────────────────────────────────────────────────────────

async def _run_loop(task_id: str, req: LoopReq) -> None:
    """
    Executes N rounds of margin borrowing in a geometric series.

    Round i borrows: initial × ratio^i
    Total ≈ initial × ratio × (1 − ratio^loops) / (1 − ratio)
    """
    task = TASKS[task_id]
    task["status"] = "running"
    log: List[str] = task["log"]

    def entry(msg: str) -> None:
        log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    try:
        ex = make_exchange(req.exchange)
        total = 0.0
        amount = req.initial

        for i in range(req.loops):
            if task.get("stop"):
                entry("已收到停止信号，终止循环")
                break

            borrow_amt = round(amount * req.ratio, 8)
            entry(f"第 {i + 1}/{req.loops} 轮：借入 {borrow_amt} {req.borrow_coin}")

            _do_borrow(ex, req.borrow_coin, borrow_amt, req.mode, req.symbol)
            total += borrow_amt
            entry(f"借入成功，累计借入：{round(total, 8)} {req.borrow_coin}")

            amount = borrow_amt          # next round borrows ratio% of this amount
            await asyncio.sleep(0.6)    # gentle rate-limit courtesy pause

        task["status"] = "done"
        task["total"] = round(total, 8)
        entry(f"✓ 循环完成，共借入 {round(total, 8)} {req.borrow_coin}")

    except Exception as e:
        task["status"] = "error"
        task["error"] = str(e)
        entry(f"[错误] {e}")


@app.post("/api/loop-borrow/start")
async def loop_start(req: LoopReq, bg: BackgroundTasks):
    tid = uuid.uuid4().hex[:8]
    TASKS[tid] = {
        "id": tid,
        "status": "pending",
        "request": req.model_dump(),
        "log": [],
        "created": datetime.now().isoformat(),
        "total": None,
        "stop": False,
    }
    bg.add_task(_run_loop, tid, req)
    return {"ok": True, "task_id": tid}


@app.get("/api/loop-borrow/tasks")
async def loop_tasks():
    return {"tasks": list(TASKS.values())}


@app.get("/api/loop-borrow/tasks/{tid}")
async def loop_task(tid: str):
    t = TASKS.get(tid)
    if not t:
        raise HTTPException(404, "任务不存在")
    return t


@app.post("/api/loop-borrow/tasks/{tid}/stop")
async def loop_stop(tid: str):
    t = TASKS.get(tid)
    if not t:
        raise HTTPException(404, "任务不存在")
    t["stop"] = True
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
