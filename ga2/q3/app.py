import time
import uuid

from fastapi import FastAPI, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

app = FastAPI()

ALLOW_ORIGIN = 'https://dash-kkv6vn.example.com'
EMAIL = '24f3001989@ds.study.iitm.ac.in'

app.add_middleware(
    CORSMiddleware, 
    allow_origins = [ALLOW_ORIGIN],
    allow_credentials = False,
    allow_methods = ['GET', 'POST'],
    allow_headers = ['*']
)

@app.middleware('http')
async def request_headers(request: Request, call_next):
    start = time.perf_counter()
    
    response = await call_next(request)

    process_time = time.perf_counter() - start

    response.headers['X-Request-ID'] = str(uuid.uuid4())
    response.headers['X-Process-Time'] = f'{process_time:.6f}'

    return response

@app.get('/stats')
async def stats(values: str = Query(...)):

    numbers = [int(value.strip()) for value in values.split(',')]

    count = len(numbers)
    total = sum(numbers)
    minimum = min(numbers)
    maximum = max(numbers)
    mean = total / count

    return {
        'email' : EMAIL,
        'count' : count,
        'sum' : total,
        'min' : minimum,
        'max' : maximum,
        'mean' : mean
    }






