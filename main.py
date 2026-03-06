"""
多交易所辅助工具 — FastAPI backend (stateless / multi-user)

Credentials are supplied by the client on every request body.
No server-side key storage — safe for shared / Railway deployments.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import ccxt
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── Supported exchanges ───────────────────────────────────────────────────────

SUPPORTED = ["binance", "okx", "bybit", "gate", "kucoin"]

# ── Exchange factory ──────────────────────────────────────────────────────────

def make_exchange(exchange: str, api_key: str, secret: str, password: str = "") -> ccxt.Exchange:
    cls = getattr(ccxt, exchange, None)
    if cls is None:
        raise HTTPException(400, f"不支持的交易所: {exchange}")
    return cls(
        {
            "apiKey": api_key,
            "secret": secret,
            "password": password,
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        }
    )


# ── Base auth model (embedded in every request that needs exchange access) ────

class Auth(BaseModel):
    exchange: str
    api_key: str
    secret: str
    password: str = ""


def ex(auth: Auth) -> ccxt.Exchange:
    return make_exchange(auth.exchange, auth.api_key, auth.secret, auth.password)


# ── Request models ────────────────────────────────────────────────────────────

class BalanceReq(Auth):
    type: str = "spot"


class OrderReq(Auth):
    symbol: str
    type: str           # "market" | "limit"
    side: str           # "buy" | "sell"
    amount: float
    price: Optional[float] = None
    params: Dict[str, Any] = {}


class OrdersListReq(Auth):
    symbol: Optional[str] = None


class CancelReq(Auth):
    order_id: str
    symbol: str


class WithdrawReq(Auth):
    coin: str
    amount: float
    address: str
    tag: Optional[str] = None
    network: Optional[str] = None


class TransferReq(Auth):
    coin: str
    amount: float
    from_account: str
    to_account: str


class BorrowReq(Auth):
    coin: str
    amount: float
    mode: str = "cross"          # "cross" | "isolated"
    symbol: Optional[str] = None  # required for isolated


class RepayReq(Auth):
    coin: str
    amount: float
    mode: str = "cross"
    symbol: Optional[str] = None


class LoopReq(Auth):
    collateral: str       # coin already held as collateral, e.g. "USDT"
    borrow_coin: str      # coin to borrow, e.g. "USDT"
    initial: float        # base amount to derive geometric series from
    ratio: float = 0.8    # fraction to borrow each round
    loops: int = 5
    mode: str = "cross"
    symbol: Optional[str] = None


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="多交易所辅助工具", version="2.0.0")
app.mount("/static", StaticFiles(directory="static"), name="static")

TASKS: Dict[str, dict] = {}   # in-memory; reset on restart (intentional)


@app.get("/", response_class=HTMLResponse)
async def root() -> str:
    with open("static/index.html", encoding="utf-8") as f:
        return f.read()


# ── Exchange list (no auth required) ─────────────────────────────────────────

@app.get("/api/exchanges")
async def list_exchanges():
    return {"supported": SUPPORTED}


# ── Balances ──────────────────────────────────────────────────────────────────

@app.post("/api/balances")
async def get_balances(req: BalanceReq):
    exchange = ex(req)
    try:
        params: dict = {}
        if req.type == "margin":
            if req.exchange == "binance":
                params = {"type": "margin"}
            elif req.exchange == "okx":
                params = {"type": "trading"}
            elif req.exchange == "bybit":
                params = {"accountType": "UNIFIED"}
        bal = exchange.fetch_balance(params)
        nonzero = {k: v for k, v in bal["total"].items() if v and float(v) > 0}
        return {"exchange": req.exchange, "type": req.type, "balances": nonzero}
    except Exception as e:
        raise HTTPException(400, str(e))


# ── Orders ────────────────────────────────────────────────────────────────────

@app.post("/api/orders/create")
async def create_order(req: OrderReq):
    exchange = ex(req)
    try:
        result = exchange.create_order(
            req.symbol, req.type, req.side, req.amount, req.price, req.params
        )
        return {"ok": True, "order": result}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/orders/list")
async def list_orders(req: OrdersListReq):
    exchange = ex(req)
    try:
        return {"orders": exchange.fetch_open_orders(req.symbol)}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/orders/cancel")
async def cancel_order(req: CancelReq):
    exchange = ex(req)
    try:
        return {"ok": True, "result": exchange.cancel_order(req.order_id, req.symbol)}
    except Exception as e:
        raise HTTPException(400, str(e))


# ── Withdraw ──────────────────────────────────────────────────────────────────

@app.post("/api/withdraw")
async def withdraw(req: WithdrawReq):
    exchange = ex(req)
    try:
        params = {}
        if req.network:
            params["network"] = req.network
        result = exchange.withdraw(req.coin, req.amount, req.address, req.tag, params)
        return {"ok": True, "result": result}
    except Exception as e:
        raise HTTPException(400, str(e))


# ── Transfer ──────────────────────────────────────────────────────────────────

@app.post("/api/transfer")
async def transfer(req: TransferReq):
    exchange = ex(req)
    try:
        result = exchange.transfer(req.coin, req.amount, req.from_account, req.to_account)
        return {"ok": True, "result": result}
    except Exception as e:
        raise HTTPException(400, str(e))


# ── Borrow / Repay helpers ────────────────────────────────────────────────────

def _do_borrow(
    exchange: ccxt.Exchange, coin: str, amount: float, mode: str, symbol: Optional[str]
) -> dict:
    try:
        return exchange.borrow_margin(coin, amount, symbol if mode == "isolated" else None, {})
    except (AttributeError, ccxt.NotSupported):
        pass
    eid = exchange.id
    if eid == "binance":
        p: dict = {"asset": coin, "amount": amount}
        if mode == "isolated" and symbol:
            p.update({"isIsolated": "TRUE", "symbol": symbol.replace("/", "")})
        return exchange.sapi_post_margin_loan(p)
    if eid == "okx":
        return exchange.private_post_account_borrow_repay(
            {"ccy": coin, "side": "borrow", "amt": str(amount)}
        )
    if eid == "bybit":
        return exchange.private_post_v5_account_borrow({"currency": coin, "qty": str(amount)})
    raise HTTPException(400, f"{eid} 暂不支持借币操作")


def _do_repay(
    exchange: ccxt.Exchange, coin: str, amount: float, mode: str, symbol: Optional[str]
) -> dict:
    try:
        return exchange.repay_margin(coin, amount, symbol if mode == "isolated" else None, {})
    except (AttributeError, ccxt.NotSupported):
        pass
    eid = exchange.id
    if eid == "binance":
        p: dict = {"asset": coin, "amount": amount}
        if mode == "isolated" and symbol:
            p.update({"isIsolated": "TRUE", "symbol": symbol.replace("/", "")})
        return exchange.sapi_post_margin_repay(p)
    if eid == "okx":
        return exchange.private_post_account_borrow_repay(
            {"ccy": coin, "side": "repay", "amt": str(amount)}
        )
    if eid == "bybit":
        return exchange.private_post_v5_account_repay({"currency": coin, "qty": str(amount)})
    raise HTTPException(400, f"{eid} 暂不支持还款操作")


@app.post("/api/borrow")
async def borrow(req: BorrowReq):
    exchange = ex(req)
    try:
        result = _do_borrow(exchange, req.coin, req.amount, req.mode, req.symbol)
        return {"ok": True, "result": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/repay")
async def repay(req: RepayReq):
    exchange = ex(req)
    try:
        result = _do_repay(exchange, req.coin, req.amount, req.mode, req.symbol)
        return {"ok": True, "result": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, str(e))


# ── Loop borrow ───────────────────────────────────────────────────────────────

async def _run_loop(task_id: str, req: LoopReq) -> None:
    """
    Geometric-series loop borrow:
      Round i borrows: initial × ratio^i
      Total ≈ initial × ratio × (1 − ratio^N) / (1 − ratio)
    Credentials live only in `req` (in-memory, never persisted).
    """
    task = TASKS[task_id]
    task["status"] = "running"
    log: List[str] = task["log"]

    def entry(msg: str) -> None:
        log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    try:
        exchange = ex(req)
        total = 0.0
        amount = req.initial

        for i in range(req.loops):
            if task.get("stop"):
                entry("已收到停止信号，终止循环")
                break

            borrow_amt = round(amount * req.ratio, 8)
            entry(f"第 {i + 1}/{req.loops} 轮：借入 {borrow_amt} {req.borrow_coin}")
            _do_borrow(exchange, req.borrow_coin, borrow_amt, req.mode, req.symbol)
            total += borrow_amt
            entry(f"借入成功，累计借入：{round(total, 8)} {req.borrow_coin}")

            amount = borrow_amt
            await asyncio.sleep(0.6)

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
    # Store only sanitized metadata — credentials are NEVER persisted
    TASKS[tid] = {
        "id": tid,
        "status": "pending",
        "request": {
            "exchange": req.exchange,
            "collateral": req.collateral,
            "borrow_coin": req.borrow_coin,
            "initial": req.initial,
            "ratio": req.ratio,
            "loops": req.loops,
            "mode": req.mode,
        },
        "log": [],
        "created": datetime.now().isoformat(),
        "total": None,
        "stop": False,
    }
    bg.add_task(_run_loop, tid, req)
    return {"ok": True, "task_id": tid}


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
