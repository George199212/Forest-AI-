"""Execution-environment-only replacement for TestClient's blocked portal.
Does not alter application source. ASGI lifecycle hooks are not started:
tests initialize their databases, and production background jobs must not run.
"""
import asyncio
import sys
sys.path.insert(0,str(__import__('pathlib').Path.cwd()))
import httpx
import fastapi.routing
import fastapi.dependencies.utils
import starlette.testclient

async def inline(fn,*args,**kwargs):
    return fn(*args,**kwargs)
fastapi.routing.run_in_threadpool=inline
fastapi.dependencies.utils.run_in_threadpool=inline

class SameThreadClient:
    def __init__(self,app,base_url='http://testserver',**kwargs):
        self.c=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=base_url,follow_redirects=True)
    def __enter__(self):return self
    def __exit__(self,*args):asyncio.run(self.c.aclose())
    @property
    def auth(self):return self.c.auth
    @auth.setter
    def auth(self,value):self.c.auth=value
    def request(self,method,url,**kw):return asyncio.run(self.c.request(method,url,**kw))
    def get(self,url,**kw):return self.request('GET',url,**kw)
    def post(self,url,**kw):return self.request('POST',url,**kw)
    def patch(self,url,**kw):return self.request('PATCH',url,**kw)
    def delete(self,url,**kw):return self.request('DELETE',url,**kw)
starlette.testclient.TestClient=SameThreadClient
import pytest
raise SystemExit(pytest.main(sys.argv[1:]))
