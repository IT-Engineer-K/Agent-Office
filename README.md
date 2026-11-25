# Agent Office (`agent-office`)

人間を中心に据えつつ、部署ごとの AI エージェント（マネージャー役・部下役）が並列に協調し、要望受付・質問すり合わせ・委譲・完了報告を行うためのオフィス基盤 CLI 兼 Python ライブラリです。

## 設計の特徴

- **`discord-msg` との責務分離**: Discord の低レベル通信は [`discord-message-cli`](https://pypi.org/project/discord-message-cli/) (`discord_msg >= 0.3.0`) へ委譲し、Agent Office は `ConversationAdapter` を介して `REQ-ID`・部署窓口（`Desk`）・登場人物（`Actor`）・ステータス遷移・SQLite 永続化を管理します。
- **人間中心＆複数部署の並列協調に対応**:
  - `Desk`（各部署の窓口＝チャンネル。登録済みチャンネルのみアクセス可能な allowlist として機能）
  - `Actor`（`human` / `manager` / `worker`）
  - `Request`（`REQ-0001` 形式の連番、`parent_req_id` による親子タスク委譲、`OPEN` / `CLARIFYING` / `WAITING_HUMAN` / `IN_PROGRESS` / `DONE` / `CANCELLED`）
  - `RequestEvent`（質問・回答・状態変更の監査ログ）
- **再開可能なカーソル管理**: 受付チャンネルの `inbox_cursor` と各スレッドの `thread_cursor` を SQLite へ永続化し、プロセス再起動後も同じ位置から再開できます。

## 導入

```powershell
pip install agent-office
```

ローカルで開発する場合はリポジトリ直下で以下を実行してください。

```powershell
pip install -e .
```

Discord と連携する場合は事前に `DISCORD_BOT_TOKEN` 環境変数を設定してください（`discord-msg setup` でも設定可能です）。

## 基本的な使い方（CLI）

全コマンドで `--format json`（AI エージェント向け）と `--format table`（人間向け・既定）を利用できます。

```powershell
# 1. 部署窓口（Desk）と登場人物（Actor）を登録
agent-office desk add dev --channel 123456789012345678 --name "開発部"
agent-office actor add owner --role human --name "オーナー" --external-user-id 222333444555666777
agent-office actor add dev-manager --role manager --name "開発マネージャー" --desk dev

# 2. 受付チャンネルの新着メッセージから REQ-ID を発番
agent-office inbox pull --desk dev --format json

# 3. 質問を送信（スレッド未作成なら自動作成、ステータスは CLARIFYING へ）
agent-office req ask REQ-0001 "優先度は高・中・低のどれにしますか？" --actor dev-manager --format json

# 4. 提案者の返信を待機（タイムアウトしてもカーソルを保存して終了コード 0）
agent-office req wait REQ-0001 --timeout 60 --format json

# 5. 進捗報告や完了報告（ステータス同時更新）
agent-office req reply REQ-0001 "実装とテストが完了しました。" --actor dev-manager --status DONE --format json
```

## Python API の利用例

```python
from agent_office import AgentOfficeService, DiscordConversationAdapter, SQLiteStore

with SQLiteStore() as store:
    svc = AgentOfficeService(store, DiscordConversationAdapter())
    pulled = svc.pull_inbox("dev")
    for req in pulled.created_requests:
        svc.ask(req.req_id, "詳細要件を確認させてください。", actor_id="dev-manager")
        waited = svc.wait_for_answer(req.req_id, timeout=60.0)
        if not waited.timed_out:
            svc.reply(req.req_id, "承知しました。作業を開始します。", actor_id="dev-manager", status="IN_PROGRESS")
```

## テストの実行

テストは `InMemoryConversationAdapter` およびモック `HttpTransport` を使用するため、外部通信なしで実行できます。

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```
