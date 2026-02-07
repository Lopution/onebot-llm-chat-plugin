
# 上下文存储测试 (Update for Context Store V2)
import pytest
import json
import aiosqlite
from pathlib import Path
from unittest.mock import patch, AsyncMock

class TestNicknameSanitization:
    """昵称清洗与身份提取测试"""
    
    @pytest.fixture
    def store(self):
        from mika_chat_core.utils.context_store import SQLiteContextStore
        return SQLiteContextStore()

    def test_sanitize_nickname_basic(self, store):
        """测试基础昵称清洗"""
        assert store._sanitize_nickname("小明") == "小明"
        assert store._sanitize_nickname("Jason") == "Jason"
        assert store._sanitize_nickname("User123") == "User123"

    def test_sanitize_nickname_emoji_symbols(self, store):
        """测试去除 Emoji 和符号"""
        assert store._sanitize_nickname("꧁༺叶良辰༻꧂") == "叶良辰"
        assert store._sanitize_nickname("🔥火神🔥") == "火神"
        assert store._sanitize_nickname("(｡･ω･｡)小红") == "小红"
        assert store._sanitize_nickname("★Admin★") == "Admin"

    def test_sanitize_nickname_prefix_removal(self, store):
        """测试移除特定前缀"""
        assert store._sanitize_nickname("群主-张三") == "张三"
        assert store._sanitize_nickname("管理员李四") == "李四"
        assert store._sanitize_nickname("admin_王五") == "王五"

    def test_sanitize_nickname_empty_fallback(self, store):
        """测试全符号清洗后回退"""
        assert store._sanitize_nickname("(*&^%$#@!)") == "神秘同学"
        assert store._sanitize_nickname("") == "同学"

    def test_sanitize_nickname_truncation(self, store):
        """测试超长昵称截断"""
        long_name = "这是一个非常非常非常长的名字起码这就十五个字了"
        cleaned = store._sanitize_nickname(long_name)
        assert len(cleaned) <= 12
        assert cleaned == "这是一个非常非常非常长的"

    def test_extract_user_identity(self, store):
        """测试从消息头提取身份"""
        # 标准格式
        uid, nick = store._extract_user_identity_from_message("[小明(123456)]: 大家好")
        assert uid == "123456"
        assert nick == "小明"

        # 包含符号的昵称（会被清洗并返回原始提取值，但 store 内部使用时会清洗，这里测试的是 extraction 方法本身）
        # Wait, the method _extract_user_identity_from_message CALLS _sanitize_nickname inside it now.
        # Let's verify the code behavior.
        uid, nick = store._extract_user_identity_from_message("[🔥火神🔥(666)]: content")
        assert uid == "666"
        assert nick == "火神"  # Should be sanitized

        # Master 标记
        uid, nick = store._extract_user_identity_from_message("[⭐Sensei]: 指令")
        assert uid == "MASTER"
        assert nick == "Sensei"

        # 无效格式
        uid, nick = store._extract_user_identity_from_message("普通的文本消息")
        assert uid is None
        assert nick is None


@pytest.mark.asyncio
class TestAnalyzeContextStore:
    """SQLiteContextStore 类综合测试"""

    async def test_init_creates_archive_table(self, temp_db_path: Path):
        """测试初始化数据库会创建 message_archive 表"""
        from mika_chat_core.utils.context_store import init_database, get_db, close_database
        
        with patch("mika_chat_core.utils.context_db.DB_PATH", temp_db_path), patch("mika_chat_core.utils.context_store.DB_PATH", temp_db_path):
            await init_database()
            db = await get_db()
            
            # 验证 contexts 表
            async with db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='contexts'") as cursor:
                assert await cursor.fetchone() is not None
                
            # 验证 message_archive 表
            async with db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='message_archive'") as cursor:
                assert await cursor.fetchone() is not None
            
            await close_database()

    async def test_add_message_archives_data(self, temp_db_path: Path, temp_database):
        """测试添加消息时会自动归档"""
        from mika_chat_core.utils.context_store import SQLiteContextStore
        
        with patch("mika_chat_core.utils.context_db.DB_PATH", temp_db_path), patch("mika_chat_core.utils.context_store.DB_PATH", temp_db_path):
            with patch("mika_chat_core.utils.context_store.get_db", return_value=temp_database):
                store = SQLiteContextStore()
                
                # 添加一条消息
                await store.add_message("user123", "user", "[小明(123)]: 早上好")
                
                # 验证 contexts (短期记忆)
                context = await store.get_context("user123")
                assert len(context) == 1
                
                # 验证 message_archive (长期记忆)
                # 注意：我们 Mock 了 get_db，所以需要直接在 temp_database 上查询
                async with temp_database.execute("SELECT * FROM message_archive") as cursor:
                    rows = await cursor.fetchall()
                    assert len(rows) == 1
                    row = rows[0]
                    # schema: id, context_key, user_id, role, content, message_id, timestamp, created_at
                    assert row[1] == "private:user123" # context_key
                    assert row[2] == "user123"         # user_id
                    assert row[3] == "user"            # role
                    assert row[4] == "[小明(123)]: 早上好" # content

    async def test_truncation_logic_pure_fifo(self, temp_db_path: Path, temp_database):
        """测试截断逻辑回归纯 FIFO (无摘要)"""
        from mika_chat_core.utils.context_store import SQLiteContextStore
        
        with patch("mika_chat_core.utils.context_db.DB_PATH", temp_db_path), patch("mika_chat_core.utils.context_store.DB_PATH", temp_db_path):
            with patch("mika_chat_core.utils.context_store.get_db", return_value=temp_database):
                max_context = 5
                store = SQLiteContextStore(max_context=max_context)
                
                # max_messages = 5 * 2 = 10
                # 添加 15 条消息
                for i in range(15):
                    await store.add_message("user123", "user", f"Msg {i}")
                
                # 获取上下文
                context = await store.get_context("user123")
                
                # 验证长度是 10
                assert len(context) == 10
                
                # 验证第一条是不是 Msg 5 (0-4被截断)
                assert context[0]["content"] == "Msg 5"
                assert context[-1]["content"] == "Msg 14"
                
                # 验证没有 System Prompt 摘要注入
                assert context[0]["role"] != "system"

    async def test_archive_preserves_truncated_messages(self, temp_db_path: Path, temp_database):
        """测试即使上下文被截断，归档表中仍保留所有消息"""
        from mika_chat_core.utils.context_store import SQLiteContextStore
        
        with patch("mika_chat_core.utils.context_db.DB_PATH", temp_db_path), patch("mika_chat_core.utils.context_store.DB_PATH", temp_db_path):
            with patch("mika_chat_core.utils.context_store.get_db", return_value=temp_database):
                store = SQLiteContextStore(max_context=2) # Limit 4 messages
                
                # 添加 10 条消息
                for i in range(10):
                    await store.add_message("user123", "user", f"Msg {i}")
                
                # 检查归档表
                async with temp_database.execute("SELECT count(*) FROM message_archive") as cursor:
                    row = await cursor.fetchone()
                    assert row[0] == 10  # 所有 10 条都在
                
                # 检查上下文表
                context = await store.get_context("user123")
                assert len(context) == 4

    async def test_multimodal_content_storage(self, temp_db_path: Path, temp_database):
        """测试多模态消息存储 (JSON 序列化)"""
        from mika_chat_core.utils.context_store import SQLiteContextStore
        
        with patch("mika_chat_core.utils.context_db.DB_PATH", temp_db_path), patch("mika_chat_core.utils.context_store.DB_PATH", temp_db_path):
            with patch("mika_chat_core.utils.context_store.get_db", return_value=temp_database):
                store = SQLiteContextStore()
                
                complex_content = [{"type": "text", "text": "Hi"}, {"type": "image", "url": "http://img"}]
                await store.add_message("user123", "user", complex_content)
                
                # 验证 Archive 表中存的是 JSON 字符串
                async with temp_database.execute("SELECT content FROM message_archive") as cursor:
                    row = await cursor.fetchone()
                    stored_content = row[0]
                    assert isinstance(stored_content, str)
                    loaded = json.loads(stored_content)
                    assert loaded[0]["text"] == "Hi"
