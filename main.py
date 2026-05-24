import os
import httpx
import datetime
import base64
import uuid
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

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
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import OrderArgs, OrderType, PartialCreateOrderOptions
        from py_clob_client.constants import POLYGON
        
        # Inicializar cliente
        client = ClobClient(
            host=CLOB_HOST,
            chain_id=order.chain_id,
            key=order.private_key,
            signature_type=3,
            funder=os.environ.get("POLY_FUNDER_ADDRESS")
        )
        
        # Derivar API credentials
        creds = client.derive_api_key()
        client.set_api_creds(creds)
        
        # Obtener token_id NO desde CLOB
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
        
        # Ejecutar orden
        result = client.create_and_post_order(
            OrderArgs(
                token_id=token_id,
                price=order.price,
                size=order.size_usdc,
            ),
            options=PartialCreateOrderOptions(tick_size="0.01")
        )
        
        return {
            "success": True,
            "order_id": result.get("orderID", ""),
            "status": result.get("status", ""),
            "token_id": token_id
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
