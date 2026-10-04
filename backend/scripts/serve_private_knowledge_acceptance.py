"""Local browser acceptance against the existing isolated test schema.

This runner never resets tables and cannot point at the development database.
The bootstrap issues an ordinary test JWT via a synthetic WeChat provider.
"""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.core.config import get_settings
from app.core.database import get_db
from app.db.base import Base
from app.main import app
from app.services.auth_service import AuthService
from app.services.knowledge_task_service import KnowledgeTaskWorker
from app.services.quiz_task_service import QuizTaskWorker
from app.api.dependencies import get_quiz_generator, get_web_search_service
from app.api.v1.routes import quizzes

configuration = get_settings().model_copy(update={'enable_knowledge_base': True})
assert make_url(configuration.test_database_url).database.endswith('_test')
assert make_url(configuration.test_database_url) != make_url(configuration.database_url)
configuration.knowledge_storage_directory = str(Path(__file__).resolve().parents[1]/'data/browser-knowledge')
configuration.chroma_persist_directory = str(Path(__file__).resolve().parents[1]/'data/browser-chroma')
engine = create_async_engine(configuration.test_database_url, hide_parameters=True)
sessions = async_sessionmaker(engine, expire_on_commit=False)
frontend = Path(__file__).resolve().parents[2]/'frontend/dist'
login_payload = None

class SyntheticWechat:
    async def code_to_session(self, code):
        return {'openid': 'isolated-browser-acceptance-user', 'unionid': ''}

async def database():
    async with sessions() as db:
        yield db

app.dependency_overrides[get_db] = database
app.dependency_overrides[get_settings] = lambda: configuration
# Existing quiz routes read configuration directly instead of through Depends.
# This isolated runner must use the same enabled flag and private directories.
quizzes.get_settings = lambda: configuration

@asynccontextmanager
async def lifespan(_):
    global login_payload
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        login_payload = await AuthService(db, configuration, SyntheticWechat()).wechat_login('synthetic-code')
    ordinary = QuizTaskWorker(sessions, configuration, get_quiz_generator, get_web_search_service)
    private = KnowledgeTaskWorker(sessions, configuration)
    ordinary.start(); private.start()
    try: yield
    finally:
        await private.close(); await ordinary.close(); await engine.dispose()

app.router.lifespan_context = lifespan

@app.get('/acceptance', response_class=HTMLResponse, include_in_schema=False)
async def entry():
    auth = {'accessToken': login_payload['access_token'], 'refreshToken': login_payload['refresh_token'], 'user': login_payload['user']}
    html = (frontend/'index.html').read_text(encoding='utf-8')
    bootstrap = '<script>localStorage.setItem("bamboo_auth_v1",'+json.dumps(json.dumps({'data': auth}, default=str))+');</script>'
    return html.replace('</head>', bootstrap+'</head>')

app.mount('/', StaticFiles(directory=frontend, html=True), name='acceptance-h5')

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8000, access_log=False)
