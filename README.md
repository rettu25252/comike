# 買い物リストサイト

このプロジェクトは、パスワードで保護された買い物リストWebアプリです。共有保存に対応しており、サーバー側の SQLite データベースに状態を保存します。

## 使い方
1. ローカルでサーバーを起動します。
   - `python manage.py runserver`
2. ブラウザで `http://127.0.0.1:8000/` を開きます。
3. 初回はパスワードを設定します。
4. リストを作成・選択し、購入状態やメモを管理できます。
5. 「戻す」「やり直す」ボタンで過去の購入状態変更を遡れます。

## 外部公開向け
- ホスティングサービスにデプロイする場合は、依存関係をインストールします。
  - `pip install -r requirements.txt`
- サービス側では `gunicorn main.wsgi:application` が起動するようにしてください。
- 必要に応じて `ALLOWED_HOSTS` に公開ドメインを設定してください。

### Django 管理画面ログイン
- 管理画面 URL は `https://<your-domain>/admin/` です。
- 本番環境では起動時に `owner` ユーザー（staff/superuser）を自動作成または更新します。
- パスワードは次の優先順で決まります。
  1. `DJANGO_SUPERUSER_PASSWORD`
  2. `SHOPPING_ADMIN_PASSWORD`
  3. `ishirettu25252`（どちらも未設定の場合の既定値）
- `createsuperuser` をローカルで実行しても、本番（Render）のデータベースには反映されません。

## 保存先
- サーバー側の SQLite データベース `shopping_list.db` に保存されます。
- 共有利用時は同じサーバーへ接続したブラウザ間で同期されます。

## GitHub 連携
- リポジトリにこのディレクトリをそのまま追加し、`git add .` でコミットできます。
- ローカルのデータベースファイルは `.gitignore` で除外しています。
