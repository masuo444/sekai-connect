# Connect-Nexus システムアーキテクチャ

## 全体構成

```
┌─────────────────────────────────────────────────────────┐
│                    Scheduler (GitHub Actions / cron)     │
│                    毎日定時に全パイプラインを実行           │
└──────────────────────┬──────────────────────────────────┘
                       │
         ┌─────────────▼─────────────┐
         │   1. News Collector        │
         │   (Gemini API)             │
         │   - Google News RSS        │
         │   - 現地メディアスクレイピング │
         │   - SNSトレンド監視          │
         └─────────────┬─────────────┘
                       │ raw news data
         ┌─────────────▼─────────────┐
         │   2. Content Generator     │
         │   (GPT-5.2 API)             │
         │   - 多言語記事生成 (JP/EN/AR)│
         │   - SNS最適化キャプション     │
         │   - ハッシュタグ自動選定      │
         │   - FOMUS導線の自然挿入      │
         └─────────────┬─────────────┘
                       │ articles + captions
         ┌─────────────▼─────────────┐
         │   3. Visual Generator      │
         │   (Google Gemini 3 Flash)      │
         │   - フォトリアル画像生成      │
         │   - 国別ブランドテンプレート   │
         │   - Connect-Nexusロゴ合成   │
         └─────────────┬─────────────┘
                       │ images
         ┌─────────────▼─────────────┐
         │   4. Content Hub           │
         │   (Airtable / SQLite)      │
         │   - 全コンテンツの一元管理    │
         │   - ステータス追跡           │
         │   - 投稿スケジュール管理      │
         └─────────────┬─────────────┘
                       │ scheduled posts
         ┌─────────────▼─────────────┐
         │   5. Multi-SNS Publisher   │
         │   - Instagram Graph API    │
         │   - TikTok Business API    │
         │   - X (Twitter) API v2     │
         │   - タイムゾーン最適化投稿    │
         └─────────────┬─────────────┘
                       │ analytics
         ┌─────────────▼─────────────┐
         │   6. Analytics & Feedback  │
         │   - エンゲージメント分析      │
         │   - 翌日のネタ選定に反映      │
         │   - A/Bテスト結果の蓄積      │
         └───────────────────────────┘
```

## ディレクトリ構成

```
connect-nexus/
├── config/
│   ├── countries.yaml        # 各国の設定 (言語, トーン, ターゲット)
│   ├── brands.yaml           # ブランド設定 (Connect Dubai等)
│   └── api_keys.env          # APIキー (.gitignore対象)
├── src/
│   ├── agents/
│   │   ├── trend_analyst.py  # Gemini 3 Flash: ニュース収集・分析
│   │   ├── copywriter.py     # GPT-5.2: 多言語記事生成
│   │   └── creative_dir.py   # Gemini 3 Flash: 画像生成
│   ├── api/
│   │   ├── gemini_client.py  # Google Gemini 3 Flash API wrapper
│   │   ├── openai_client.py  # OpenAI GPT-5.2 wrapper
│   │   └── imagen_client.py  # Google Gemini 3 Flash 画像生成 wrapper
│   ├── database/
│   │   ├── models.py         # データモデル定義
│   │   └── airtable_sync.py  # Airtable連携
│   ├── sns/
│   │   ├── instagram.py      # Instagram自動投稿
│   │   ├── tiktok.py         # TikTok自動投稿
│   │   └── twitter.py        # X(Twitter)自動投稿
│   ├── content/
│   │   ├── templates/        # 記事テンプレート
│   │   └── prompts/          # AIプロンプト集
│   └── pipeline.py           # メインパイプライン
├── docs/
│   ├── BUSINESS_MODEL.md     # ビジネスモデル
│   └── SYSTEM_ARCHITECTURE.md # 本ドキュメント
├── data/
│   ├── news/                 # 収集ニュースデータ
│   ├── articles/             # 生成記事データ
│   └── images/               # 生成画像データ
├── requirements.txt
├── .env.example
└── README.md
```

## 技術スタック

| レイヤー | 技術 | 理由 |
|---------|------|------|
| 言語 | Python 3.11+ | AI/ML エコシステムが最も充実 |
| AIエージェント | CrewAI (OpenCrew) | マルチエージェント協調に最適 |
| LLM (リサーチ) | Google Gemini API | 長文処理・Web検索に強い |
| LLM (執筆) | OpenAI GPT-5.2 | 高品質な多言語コピーライティング |
| 画像生成 | Google Gemini 3 Flash | フォトリアル・API安定性 |
| データベース | SQLite + Airtable | ローカル高速 + 可視化管理 |
| スケジューラ | GitHub Actions / cron | 無料・安定した定期実行 |
| デプロイ | VPS (最小構成) | 月500円程度で24時間稼働 |

## API コスト見積もり (月間)

| API | 使用量/月 | 単価 | 月額 |
|-----|---------|------|------|
| Gemini API | 3000リクエスト | 無料枠内 | ~0円 |
| GPT-5.2 | 500記事相当 | ~$0.005/1K tokens | ~3,000円 |
| Gemini 3 Flash (画像) | 300枚 | ~$0.02/枚 | ~1,000円 |
| **合計** | | | **~4,000円** |

## 多国展開の仕組み

```yaml
# config/countries.yaml の例
countries:
  dubai:
    name: "Connect Dubai"
    languages: ["ja", "en", "ar"]
    tone: "investment-luxury"
    topics: ["real-estate", "tax", "lifestyle", "business"]
    timezone: "Asia/Dubai"  # UTC+4
    prime_time: ["08:00", "12:00", "20:00"]

  saudi:
    name: "Connect Saudi"
    languages: ["ja", "en", "ar"]
    tone: "culture-business"
    topics: ["vision2030", "japanese-culture", "mega-projects", "halal"]
    timezone: "Asia/Riyadh"  # UTC+3
    prime_time: ["09:00", "13:00", "21:00"]

  brunei:
    name: "Connect Brunei"
    languages: ["ja", "en", "ms"]
    tone: "royal-tradition"
    topics: ["royal-family", "halal-japan", "craftsmanship", "luxury"]
    timezone: "Asia/Brunei"  # UTC+8
    prime_time: ["08:00", "12:00", "19:00"]
```
