# 🎙️ System Output Audio Recorder (Silicon Valley Edition)

Windows 11（およびmacOS）の標準出力（スピーカー・ヘッドホンから流れるシステム音声）を高音質で直接キャプチャ・録音し、WAVおよび各種圧縮形式（MP3, AAC, FLAC, OGG, Opus）で保存する次世代デスクトップアプリケーションです。

---

## ✨ 主な特徴・すごい機能

1. **⚡ ゼロ遅延・高音質 WASAPI Loopback 録音 (Windows 11)**
   - 外部仮想オーディオドライバ不要。Windows 11のCoreAudioエンジンから直接ロスレスキャプチャ。
2. **🕒 タイムシフト録音（遡り録音 / Pre-Recording）**
   - 常に直前30秒〜1分間の音声をメモリ上の**Lock-Free RingBuffer**に保持。「あ、今の音声を録音したかった！」と思った瞬間に録音ボタンを押せば、**ボタンを押す前の音声を含めて保存**可能。
3. **💾 WAV & 多彩な圧縮フォーマット対応**
   - **WAV (PCM 16-bit / ロスレス)**
   - **MP3 (最高320kbps)**
   - **AAC / M4A (高圧縮・高音質)**
   - **FLAC (完全可逆圧縮)**
   - **OGG / Opus**
4. **📊 リアルタイム 60fps モニター**
   - ステレオ音量レベルメーター（ピークホールド & クリッピング検知LED）
   - グローエフェクト付き波形オシロスコープ
5. **✂️ スマート無音検出 & 自動スキップ (VAD)**
   - 音声がない無音区間を自動判定。
6. **📌 タイムスタンプ・マーカー機能**
   - 録音中の重要ポイントにワンクリックでブックマークを打てる。
7. **🤖 AI文字起こし & 翻訳 & 字幕生成 (TODO拡張)**
   - faster-whisper による高速ローカル文字起こし
   - Google Gemini API による多言語翻訳・議事録要約
   - **SRT / WebVTT / Markdown** 形式でのワンクリック出力

---

## 🚀 クイックスタート

### 1. 仮想環境の有効化 & 依存パッケージのインストール
```bash
# 仮想環境の作成 (Python 3.10 - 3.12 推奨)
py -3.12 -m venv .venv

# 依存パッケージのインストール
.venv\Scripts\pip install -r requirements.txt
```

### 2. アプリケーションの起動
```bash
# 通常起動 (Windows 11 WASAPI Loopback)
.venv\Scripts\python main.py

# モックモード (音声デバイスのないCI環境やシミュレーション用)
.venv\Scripts\python main.py --mock
```

### 3. テストの実行
```bash
.venv\Scripts\pytest -v
```

---

## 📐 アーキテクチャ構成

OBS等の既存コードの丸写しを完全に排除し、**Clean Architecture（ヘキサゴナル・アーキテクチャ）**と**Reactive Streams**を採用したオリジナル設計です。

```text
default_output_recorder/
├── src/
│   ├── core/               # 🧠 ドメイン層 (モデル, RingBuffer, Pipeline, StateMachine, EventBus)
│   ├── drivers/            # 🔌 ハードウェア抽象化層 (WASAPI Loopback, Mock)
│   ├── encoders/           # 💾 音声エンコード (WAV, MP3, AAC, FLAC, OGG, Opus)
│   ├── ai/                 # 🤖 AI文字起こし & 翻訳 & 字幕エクスポーター
│   └── ui/                 # 🎨 PySide6 モダンUI (LevelMeter, Visualizer, History)
├── tests/                  # 🧪 pytest ユニット・結合テスト
├── main.py                 # 🚀 アプリ起動エントリーポイント
└── requirements.txt        # 📦 依存関係
```
