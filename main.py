import os
import httpx
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel

app = FastAPI()
CLOB_HOST = "https://clob.polymarket.com"
API_SECRET = os.environ.get("EXECUTOR_SECRET", "changeme")

class OrderRequest(BaseModel):
    market_id: str
    price: float
    size_usdc: float
    private_key: str
    chain_id: int = 137

@app.get("/health")
async def health():
    return {"status": "ok", "region": "europe"}

@app.get("/test-polymarket")
async def test_polymarket():
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{CLOB_HOST}/time", timeout=10)
        return {"status": r.status_code, "blocked": r.status_code == 403}

@app.post("/execute-order")
async def execute_order(order: OrderRequest, x_secret: str = Header(None)):
    if x_secret != API_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        from py_clob_client_v2 import ClobClient, OrderArgs, OrderType, PartialCreateOrderOptions, Side

        # Paso 1 — obtener credenciales L2
        client_l1 = ClobClient(
            host=CLOB_HOST,
            chain_id=order.chain_id,
            key=order.private_key,
        )
        creds = client_l1.create_or_derive_api_key()

        # Paso 2 — cliente autenticado L1+L2
        client = ClobClient(
            host=CLOB_HOST,
            chain_id=order.chain_id,
            key=order.private_key,
            creds=creds,
        )

        # Resolver token_id NO
        if order.market_id.startswith("0x"):
            async with httpx.AsyncClient() as http:
                r = await http.get(f"{CLOB_HOST}/markets/{order.market_id}", timeout=10)
                if r.status_code != 200:
                    raise HTTPException(status_code=422, detail=f"Market not found: {order.market_id}")
                market_data = r.json()
                tokens = market_data.get("tokens", [])
                token_id = None
                for token in tokens:
                    if token.get("outcome", "").lower() == "no":
                        token_id = token["token_id"]
                        break
                if not token_id and len(tokens) >= 2:
                    token_id = tokens[1]["token_id"]
                if not token_id:
                    raise HTTPException(status_code=422, detail="No token_id found")
        else:
            token_id = order.market_id

        # Ejecutar orden
        resp = client.create_and_post_order(
            order_args=OrderArgs(
                token_id=token_id,
                price=order.price,
                size=order.size_usdc,
                side=Side.BUY,
            ),
            options=PartialCreateOrderOptions(tick_size="0.01"),
            order_type=OrderType.GTC,
        )

        return {
            "success": True,
            "order_id": resp.get("orderID", ""),
            "status": resp.get("status", ""),
            "token_id": token_id,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
