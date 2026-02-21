"""UAE関連記事10本をDBに投入し、静的サイトを生成するシードスクリプト。"""

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "data" / "connect_nexus.db"

# --- 10本のUAE記事データ ---
TODAY = datetime.now(timezone.utc)

ARTICLES = [
    {
        "days_ago": 0,
        "title": "ドバイ不動産市場、2026年上半期も二桁成長を維持",
        "body": (
            "ドバイ土地局（DLD）の最新データによると、2026年上半期の不動産取引額は"
            "前年同期比18%増の2,100億ディルハム（約8.4兆円）に達した。\n\n"
            "特にパーム・ジュメイラやダウンタウン地区の高級物件が牽引役となっており、"
            "日本人投資家の問い合わせも過去最高を記録している。\n\n"
            "現地の不動産コンサルタントは「ゴールデンビザ制度の拡充と法人税0%の環境が、"
            "アジアからの投資を加速させている」と分析する。\n\n"
            "物件価格は2020年の底値から平均65%上昇しているが、ロンドンやシンガポールと"
            "比較すると依然として割安感があり、今後も上昇基調が続く見通しだ。"
        ),
        "caption": "ドバイ不動産市場が2026年も絶好調。日本人投資家の参入が急増中。",
        "hashtags": "#ドバイ不動産 #海外投資 #ゴールデンビザ #ConnectDubai #UAE",
        "source": "https://www.dld.gov.ae",
    },
    {
        "days_ago": 1,
        "title": "UAE、日本企業向けフリーゾーン優遇策を発表",
        "body": (
            "UAE経済省は、日本企業のUAE進出を促進するため、主要フリーゾーンにおける"
            "新たな優遇策を発表した。\n\n"
            "具体的には、DMCC（ドバイ・マルチ・コモディティーズ・センター）とJAFZA"
            "（ジェベルアリ・フリーゾーン）において、日本企業向けに初年度ライセンス費用の"
            "50%減額、オフィススペースの3ヶ月無料提供が適用される。\n\n"
            "在ドバイ日本国総領事館によると、UAEに拠点を持つ日本企業は現在約450社。"
            "2027年末までに600社を目標としている。\n\n"
            "中東を拠点にアフリカ・南アジア市場へのアクセスを狙う日本企業にとって、"
            "この優遇策は大きな追い風となりそうだ。"
        ),
        "caption": "UAE、日本企業向けにフリーゾーン優遇策。初年度50%割引の衝撃。",
        "hashtags": "#UAE進出 #フリーゾーン #日本企業 #DMCC #ConnectDubai",
        "source": "https://www.economy.gov.ae",
    },
    {
        "days_ago": 3,
        "title": "ドバイ発・日本の伝統工芸品がアラブ富裕層に人気急上昇",
        "body": (
            "ドバイモールに昨年オープンした日本工芸品セレクトショップ「TAKUMI」が、"
            "月商1,000万ディルハム（約4億円）を突破した。\n\n"
            "特に人気なのは、有田焼の茶器セット、輪島塗の漆器、そして岐阜県産の枡（ます）。"
            "枡は日本酒を注ぐ伝統的な器だが、ドバイではインテリアやギフトとして再解釈され、"
            "金箔仕上げの限定モデルは即完売が続いている。\n\n"
            "アラブ首長国連邦では「メイド・イン・ジャパン」への信頼が非常に高く、"
            "職人の手仕事による一点物に対して惜しみなく投資する文化がある。\n\n"
            "日本の地方自治体からも注目が集まっており、今後は石川県や新潟県の工芸品も"
            "ラインナップに加わる予定だ。"
        ),
        "caption": "ドバイで日本の伝統工芸品が大ブーム。枡や漆器が富裕層の心を掴む。",
        "hashtags": "#日本工芸 #ドバイ #伝統文化 #メイドインジャパン #ConnectDubai",
        "source": "https://www.arabianbusiness.com",
        "has_fomus": True,
    },
    {
        "days_ago": 5,
        "title": "ゴールデンビザ取得者が100万人突破、日本人申請も倍増",
        "body": (
            "UAE内務省は、ゴールデンビザ（10年長期居住ビザ）の累計発行数が100万件を"
            "突破したと発表した。\n\n"
            "ゴールデンビザは不動産投資（200万ディルハム以上）、起業家、専門職、"
            "優秀な学生などを対象に発行される長期居住許可で、スポンサー不要で"
            "UAE内での自由な経済活動が可能になる。\n\n"
            "日本人の申請数は2025年比で約2倍に増加。特に不動産投資経由の取得が多く、"
            "「節税」と「資産の国際分散」を目的とする経営者層が中心だ。\n\n"
            "申請はICA（連邦身分・国籍庁）のオンラインポータルから可能で、"
            "審査期間は通常2〜4週間。家族の帯同も認められている。"
        ),
        "caption": "UAEゴールデンビザが100万人突破。日本人の申請が急増している理由とは。",
        "hashtags": "#ゴールデンビザ #UAE移住 #海外移住 #節税 #ConnectDubai",
        "source": "https://www.ica.gov.ae",
    },
    {
        "days_ago": 7,
        "title": "アブダビ、世界初のAI特区を設立 — 日本のスタートアップにも門戸",
        "body": (
            "アブダビ政府は、マスダールシティ内に世界初の「AI特区」を正式に設立した。"
            "AI企業に対して法人税免除、データセンター優遇料金、専用ビザ制度が適用される。\n\n"
            "特区にはすでにGoogle DeepMind、OpenAI、Anthropicのリサーチ拠点が入居を"
            "決定しており、2026年末までに200社の入居を目指す。\n\n"
            "日本のAIスタートアップにも積極的な誘致が行われており、JETRO（日本貿易振興機構）"
            "を通じた説明会が東京・大阪で開催予定。\n\n"
            "アブダビのAI戦略責任者は「日本の製造業AI、ロボティクス技術は世界最高水準。"
            "中東とのシナジーは計り知れない」とコメントしている。"
        ),
        "caption": "アブダビにAI特区が誕生。法人税ゼロで日本のスタートアップを誘致中。",
        "hashtags": "#アブダビ #AI特区 #スタートアップ #テック #ConnectDubai",
        "source": "https://www.tamm.abudhabi",
    },
    {
        "days_ago": 10,
        "title": "ドバイの教育移住が加速 — 日本人学校の定員が2倍に拡大",
        "body": (
            "ドバイ日本人学校は2026年度の入学者数が過去最多を記録し、校舎の増築を決定した。"
            "定員はこれまでの400名から800名に倍増する。\n\n"
            "背景には、ドバイへの家族帯同での移住増加がある。特にIT企業経営者や"
            "フリーランスのリモートワーカーが、子供の多言語教育と税制メリットを求めて"
            "ドバイを選ぶケースが増えている。\n\n"
            "ドバイには200校以上のインターナショナルスクールがあり、英語・アラビア語に"
            "加えてフランス語、ドイツ語、中国語のカリキュラムも選択可能。\n\n"
            "教育費は年間50万〜300万円と幅広いが、所得税ゼロの環境を考慮すると"
            "実質的な家計負担は日本より軽いケースも多い。"
        ),
        "caption": "ドバイ日本人学校が定員倍増。教育移住という新しいライフスタイル。",
        "hashtags": "#ドバイ移住 #教育移住 #海外子育て #インター校 #ConnectDubai",
        "source": "https://www.djsu.ae",
    },
    {
        "days_ago": 14,
        "title": "UAE法人設立のすべて — 最短3日で完了する手続きガイド",
        "body": (
            "UAEでの法人設立は、世界でもっとも簡単かつ迅速な国の一つだ。"
            "フリーゾーンを利用すれば、外国人100%出資が可能で、最短3営業日で"
            "会社設立が完了する。\n\n"
            "主な法人形態は以下の3つ：\n"
            "1. フリーゾーン法人 — 外国人100%所有、法人税0%（一部対象外あり）\n"
            "2. メインランド法人 — UAE国内市場で直接取引可能\n"
            "3. オフショア法人 — 資産保全・持株会社向け\n\n"
            "初期費用はフリーゾーン法人の場合、年間ライセンス料が約15,000〜50,000ディルハム"
            "（約60万〜200万円）。バーチャルオフィスを利用すれば大幅にコストを抑えられる。\n\n"
            "日本の税理士と連携した二重課税回避のスキーム構築も一般的になってきている。"
        ),
        "caption": "UAE法人設立は最短3日。日本人経営者のための完全ガイド。",
        "hashtags": "#UAE法人設立 #フリーゾーン #海外起業 #法人税ゼロ #ConnectDubai",
        "source": "https://www.moec.gov.ae",
    },
    {
        "days_ago": 18,
        "title": "ドバイ万博レガシー地区「Expo City」が第2フェーズへ — 日本館跡地の活用計画",
        "body": (
            "2020年ドバイ万博の跡地「Expo City Dubai」が第2フェーズの開発計画を発表した。"
            "総投資額は250億ディルハム（約1兆円）規模。\n\n"
            "日本館の跡地には、日本文化体験センターとジャパン・イノベーション・ハブが"
            "建設される計画で、日本の自治体や企業の常設展示スペースとなる予定だ。\n\n"
            "Expo Cityはすでにサステナビリティ関連企業やテック企業の集積地として"
            "機能しており、シーメンス・エナジーやDP Worldなどが本社を移転済み。\n\n"
            "メトロのExpo 2020駅直結というアクセスの良さもあり、"
            "ビジネスと観光の両面で注目度が高まっている。"
        ),
        "caption": "Expo City Dubai第2フェーズ始動。日本館跡地に文化センター計画。",
        "hashtags": "#ExpoCityDubai #ドバイ万博 #日本文化 #都市開発 #ConnectDubai",
        "source": "https://www.expocitydubai.com",
    },
    {
        "days_ago": 22,
        "title": "ドバイの飲食ビジネス最前線 — ラーメン店が月商3,000万円の衝撃",
        "body": (
            "ドバイのJBR（ジュメイラ・ビーチ・レジデンス）に出店した日本のラーメンチェーンが、"
            "オープン初月で月商3,000万円を記録し、業界に衝撃を与えている。\n\n"
            "ドバイの外食市場は年間成長率12%と世界でもトップクラス。人口の85%が外国人で"
            "構成されるこの都市では、多国籍料理への需要が非常に高い。\n\n"
            "日本食レストランはドバイ全体で約350店舗に増加しており、寿司・ラーメン・"
            "焼肉に加えて、最近ではおにぎり専門店やたこ焼き店も人気を集めている。\n\n"
            "飲食ライセンスの取得はフリーゾーンまたはDED（ドバイ経済観光局）経由で"
            "可能だが、酒類提供にはアルコールライセンスが別途必要となる。"
        ),
        "caption": "ドバイのラーメン店が月商3,000万円。日本食ビジネスの可能性。",
        "hashtags": "#ドバイ飲食 #ラーメン #日本食 #海外出店 #ConnectDubai",
        "source": "https://www.visitdubai.com",
    },
    {
        "days_ago": 28,
        "title": "2026年版・ドバイ生活コスト完全比較 — 東京 vs ドバイ",
        "body": (
            "ドバイへの移住を検討する日本人が増える中、実際の生活コストを東京と"
            "徹底比較した。（2026年2月時点、2人家族想定）\n\n"
            "■ 住居費\n"
            "東京（港区2LDK）: 月35万円\n"
            "ドバイ（マリーナ2BR）: 月30万円（年間約120,000 AED）\n\n"
            "■ 食費\n"
            "東京: 月12万円\n"
            "ドバイ: 月10万円（外食は高め、自炊は安め）\n\n"
            "■ 交通費\n"
            "東京: 月2万円\n"
            "ドバイ: 月3万円（車社会、ガソリンは安い）\n\n"
            "■ 税金\n"
            "東京: 所得税+住民税で実効30〜45%\n"
            "ドバイ: 所得税0%、VAT5%のみ\n\n"
            "総合すると、額面年収2,000万円の場合、ドバイの方が手取りで約500万円多くなる"
            "計算だ。この差額で不動産投資やゴールデンビザ取得に充てるケースが一般的。"
        ),
        "caption": "東京 vs ドバイ生活コスト完全比較。所得税ゼロの圧倒的メリット。",
        "hashtags": "#ドバイ生活 #生活コスト #東京比較 #海外移住 #ConnectDubai",
        "source": "https://www.numbeo.com",
    },
]


def main():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # テーブルが無ければ作成
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS news_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        country TEXT NOT NULL, title TEXT NOT NULL, url TEXT,
        source TEXT, summary TEXT, relevance_score REAL DEFAULT 0,
        collected_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'new'
    );
    CREATE TABLE IF NOT EXISTS articles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        news_item_id INTEGER REFERENCES news_items(id),
        country TEXT NOT NULL, language TEXT NOT NULL,
        platform TEXT NOT NULL, title TEXT NOT NULL,
        body TEXT, caption TEXT, hashtags TEXT,
        has_fomus_mention INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft'
    );
    CREATE TABLE IF NOT EXISTS visual_assets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        article_id INTEGER REFERENCES articles(id),
        image_path TEXT NOT NULL, prompt_used TEXT,
        aspect_ratio TEXT, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS distribution_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        article_id INTEGER REFERENCES articles(id),
        visual_asset_id INTEGER REFERENCES visual_assets(id),
        platform TEXT NOT NULL, scheduled_time TEXT NOT NULL,
        timezone TEXT, published_at TEXT,
        status TEXT NOT NULL DEFAULT 'pending'
    );
    """)
    conn.commit()

    count = 0
    for art in ARTICLES:
        ts = (TODAY - timedelta(days=art["days_ago"])).isoformat()

        # 1. news_item
        cur = conn.execute(
            "INSERT INTO news_items (country,title,url,source,summary,relevance_score,collected_at,status) VALUES (?,?,?,?,?,?,?,?)",
            ("dubai", art["title"], art["source"], art["source"],
             art["body"][:200], 8.5, ts, "processed"),
        )
        news_id = cur.lastrowid

        # 2. article (web, ja, published)
        cur = conn.execute(
            "INSERT INTO articles (news_item_id,country,language,platform,title,body,caption,hashtags,has_fomus_mention,created_at,status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (news_id, "dubai", "ja", "web", art["title"], art["body"],
             art["caption"], art["hashtags"],
             int(art.get("has_fomus", False)), ts, "published"),
        )
        article_id = cur.lastrowid

        # 3. visual_asset (placeholder)
        conn.execute(
            "INSERT INTO visual_assets (article_id,image_path,prompt_used,aspect_ratio,created_at) VALUES (?,?,?,?,?)",
            (article_id, f"[placeholder]", f"UAE article: {art['title']}", "1:1", ts),
        )

        count += 1

    conn.commit()
    conn.close()
    print(f"✓ {count} 本のUAE記事をDBに投入しました")


if __name__ == "__main__":
    main()
