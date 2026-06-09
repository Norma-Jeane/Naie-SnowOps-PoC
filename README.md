# 奈井江町除雪計画支援アプリ (Naie-SnowOps-PoC)

本リポジトリは、奈井江町における除雪計画および気象推論・道路選定の最適化支援を行うStreamlitアプリケーションの概念実証（PoC）用クリーンアップ版リポジトリです。

## 概要
気象庁から取得した気象情報をベースとした降雪レベル推定モデル（Random Forest）、および地図上での除雪ルートの算出・再計算等のシミュレーション機能を統合したWebアプリケーションを提供します。

## フォルダ構成
本プロジェクトは、アプリ実行に必要なアセットに絞ってクリーンアップされています。
```text
Naie-SnowOps-PoC/
├── Data/
│   ├── app_init/          # アプリ起動時にロードする初期データ（道路地図geojson、地図スタイル）
│   └── models/            # 学習済みの気象推論モデル (rf_level_model.joblib)
├── src/
│   ├── app/
│   │   ├── app.py         # アプリ本体のエントリポイント
│   │   ├── components/    # カスタムマップコンポーネント
│   │   └── services/      # 気象取得、ルート再計算等の各種ビジネスロジック
│   ├── common/            # 共通ヘルパー
│   └── config/            # 設定ファイル (locations.json)
├── requirements.txt       # 依存パッケージ一覧
├── .gitignore             # 構成管理除外ルール
└── README.md              # 本ドキュメント
```

## セットアップと実行方法

### 動作環境
- Python 3.9 以上
- Node.js (カスタムマップコンポーネントを開発・再ビルドする場合のみ)

### 1. 依存ライブラリのインストール
リポジトリのルートディレクトリで以下を実行します：
```bash
pip install -r requirements.txt
```

### 2. アプリの起動
以下を実行することで、ローカルでStreamlitアプリを起動できます：
```bash
python -m streamlit run src/app/app.py
```
起動後、ブラウザで `http://localhost:8501` にアクセスしてください。

## デプロイについて（Streamlit Community Cloud）
本リポジトリは Streamlit Community Cloud へ直接デプロイすることが可能です。
- デプロイの際、GitHubリポジトリ（Public）と連携し、エントリポイントを `src/app/app.py` に指定します。
- APIキー等の機密情報がある場合は、コード内に記述せず、Streamlitの管理画面（Secrets機能）に設定してください。
