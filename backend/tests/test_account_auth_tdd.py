from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from backend.app import auth, main
from backend.app.blackboard import SQLiteBlackboard
from backend.app.config import Settings


def test_settings(root: Path, **updates) -> Settings:
    base = Settings(
        qwen_api_key="",
        qwen_base_url="https://provider.invalid/v1",
        qwen_model="qwen3.8-max",
        qwen_temperature=0.1,
        qwen_secret_source="none",
        qwen_secret_error="",
        workspace_name="test",
        workspace_id="",
        vision_max_pages=24,
        external_engine_token="",
        asset_public_base_url="",
        asset_access_token="",
        mindmap_data_dir=root,
        blackboard_path=root / "blackboard.sqlite3",
        workbench_owner_id="public-workbench",
    )
    return base.__class__(**{**base.__dict__, **updates})


class AccountStoreTDDTests(unittest.TestCase):
    def test_accounts_have_independent_sessions_and_passwords_are_hashed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = auth.AccountStore(Path(temp_dir) / "auth.sqlite3")
            account_a, token_a, first_a = store.register("Alice", "a-secure-password")
            account_b, token_b, first_b = store.register("Bob", "b-secure-password")

            self.assertNotEqual(account_a.id, account_b.id)
            self.assertNotEqual(token_a, token_b)
            self.assertTrue(first_a)
            self.assertFalse(first_b)
            self.assertEqual(store.authenticate(token_a).id, account_a.id)
            self.assertEqual(store.authenticate(token_b).id, account_b.id)
            with store._connect() as connection:
                row = connection.execute(
                    "SELECT password_digest FROM users WHERE user_id = ?",
                    (account_a.id,),
                ).fetchone()
            self.assertNotIn(b"a-secure-password", bytes(row["password_digest"]))

    def test_invalid_credentials_and_duplicate_usernames_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = auth.AccountStore(Path(temp_dir) / "auth.sqlite3")
            store.register("Alice", "a-secure-password")
            with self.assertRaises(auth.AccountAlreadyExistsError):
                store.register(" alice ", "another-password")
            with self.assertRaises(auth.InvalidCredentialsError):
                store.login("Alice", "wrong-password")

    def test_legacy_owner_records_can_be_claimed_by_first_account(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            board = SQLiteBlackboard(root / "blackboard.sqlite3")
            board.upsert_job(
                task_id="task-legacy",
                status="completed",
                stage="complete",
                progress=100,
                message="done",
                mode="standard",
                owner_id="public-workbench",
            )
            board.upsert_job(
                task_id="task-old-empty",
                status="completed",
                stage="complete",
                progress=100,
                message="done",
                mode="standard",
                owner_id="",
            )
            store = auth.AccountStore(root / "auth.sqlite3")
            account, _, first_account = store.register("Alice", "a-secure-password")
            self.assertTrue(first_account)

            board.reassign_owner("public-workbench", account.id)
            board.reassign_owner("", account.id)

            self.assertIsNotNone(
                board.load_job("task-legacy", owner_id=account.id)
            )
            self.assertIsNotNone(
                board.load_job("task-old-empty", owner_id=account.id)
            )


class AccountRouteTDDTests(unittest.IsolatedAsyncioTestCase):
    async def test_register_login_logout_and_owner_isolation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            configured = test_settings(root)
            board = SQLiteBlackboard(configured.blackboard_path)
            account_store = auth.AccountStore(root / "auth.sqlite3")

            with (
                patch.object(main, "settings", configured),
                patch.object(auth, "settings", configured),
                patch.object(main, "blackboard", board),
                patch.object(auth, "_stores", {configured.mindmap_data_dir / "auth.sqlite3": account_store}),
            ):
                transport = httpx.ASGITransport(app=main.app)
                async with httpx.AsyncClient(
                    transport=transport,
                    base_url="http://testserver",
                ) as client_a, httpx.AsyncClient(
                    transport=transport,
                    base_url="http://testserver",
                ) as client_b:
                    unauthenticated = await client_a.get("/api/history")
                    self.assertEqual(unauthenticated.status_code, 401)

                    registered_a = await client_a.post(
                        "/api/auth/register",
                        json={
                            "username": "Alice",
                            "password": "a-secure-password",
                        },
                    )
                    board.upsert_job(
                        task_id="task-created-after-first-account",
                        status="completed",
                        stage="complete",
                        progress=100,
                        message="legacy owner created after first account",
                        mode="standard",
                        owner_id="public-workbench",
                    )
                    registered_b = await client_b.post(
                        "/api/auth/register",
                        json={
                            "username": "Bob",
                            "password": "b-secure-password",
                        },
                    )
                    self.assertEqual(registered_a.status_code, 200)
                    self.assertEqual(registered_b.status_code, 200)

                    account_a = registered_a.json()
                    account_b = registered_b.json()
                    self.assertNotEqual(account_a["id"], account_b["id"])

                    board.upsert_job(
                        task_id="task-a",
                        status="completed",
                        stage="complete",
                        progress=100,
                        message="done",
                        mode="standard",
                        owner_id=account_a["id"],
                    )
                    board.upsert_job(
                        task_id="task-b",
                        status="completed",
                        stage="complete",
                        progress=100,
                        message="done",
                        mode="standard",
                        owner_id=account_b["id"],
                    )

                    history_a = await client_a.get("/api/history")
                    history_b = await client_b.get("/api/history")
                    self.assertEqual(
                        [item["task_id"] for item in history_a.json()],
                        ["task-a"],
                    )
                    self.assertEqual(
                        [item["task_id"] for item in history_b.json()],
                        ["task-b"],
                    )
                    self.assertEqual(
                        (await client_a.get("/api/jobs/task-b")).status_code,
                        404,
                    )

                    logged_out = await client_a.post("/api/auth/logout")
                    self.assertEqual(logged_out.status_code, 200)
                    self.assertEqual(
                        (await client_a.get("/api/history")).status_code,
                        401,
                    )


if __name__ == "__main__":
    unittest.main()
