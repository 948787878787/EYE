# EYE：台灣行人號誌與斑馬線辨識（視障者過馬路輔助，K230）

**EYE** 是一個高中專題，目標是做一個**開源**的過馬路輔助裝置，給視障者使用：
- 小型 AI 板 **CanMV K230** 即時判讀**行人號誌**（紅燈、綠燈、綠燈閃爍）；
- 同時判讀**斑馬線方向**；
- 用中文語音告訴使用者。

> ⚠️ **安全聲明**
> - 這是研究原型，**沒有經過任何安全認證**，不能取代白手杖、導盲犬、有聲號誌或他人協助。
> - 程式的設計原則是「**不確定就不報綠燈**」：沒有聲音，代表不要開始穿越。

[English below](#english)

## 這個 repo 有什麼

```
EYE/
├── README.md
├── CITATION.cff               引用格式
├── LICENSE                    程式碼：MIT
├── board/                     K230（CanMV，MicroPython）上執行的程式
├── tests/                     板子程式的邏輯測試（在電腦上用 pytest 跑）
├── tools/                     語音提示產生、黑盒子紀錄驗證
└── dataset/
    ├── README.md              資料說明、類別、格式
    ├── LICENSE                標註：CC BY-NC 4.0
    ├── labels/                類別名稱
    ├── crosswalk_tw/          台灣斑馬線中線標註（近端、遠端兩點）
    └── script/                下載照片、轉成 YOLO 格式
```

**照片不放在這個 repo**。照片放在作者公開的 Roboflow 資料集（CC BY 4.0），用 `dataset/script/download_roboflow.py` 下載，見 [dataset/README.md](dataset/README.md)。

## 系統怎麼運作

| 階段 | 模型／方法 | 說明 |
|---|---|---|
| 1. 找號誌 | YOLO26n 偵測（640×640 輸入） | 在使用者正前方的畫面範圍內找行人號誌 |
| 2. 判顏色 | YOLO11n-cls 分類（96×96） | 對號誌裁切圖判斷綠／紅／其他，再用紅光檢查否決可疑的綠燈 |
| 3. 時間投票 | `board/ped_logic_v4.py` | 多幀投票才會報綠燈；看到紅燈或可疑情況，3 秒內不報綠 |
| 4. 斑馬線（影子模式） | YOLO26n-pose（320×320，近端／遠端兩點） | v16 只記錄、不影響報出的結果，用來在實地收集證據 |
| 5. 語音與安全回饋 | `voice_v2`、`guide_v2`、`health_v1` | 綠燈時每秒滴答聲；相機太暗或被遮住會說出來；程式卡住會警告 |

板子程式版本：
- `ped_light_v15_bbox.py`：目前的主程式。
- `ped_light_v16_cwshadow.py`：v15 加上斑馬線影子模式；需要斑馬線 kmodel。
- `main_launcher_v4.py`：開機選單。預設啟動最新的讀取程式；開機時按住按鍵則改成拍照收集資料。

## 在電腦上跑測試

```bash
pip install pytest numpy
python -m pytest -q tests
```

板子專用的模組（`media`、`nncase_runtime` 等）只在 K230 上才有。測試只涵蓋純邏輯的部分。

## 放到 K230 上

1. CanMV K230 韌體 v1.8。
2. 把 `board/*.py` 複製到 SD 卡的 `/sdcard/ped_light/`，再把 `main_launcher_v4.py` 存成 `/sdcard/main.py`。
3. **模型（kmodel）目前沒有公開**：訓練資料含有作者自拍、不能公開的照片，模型能不能公開還在確認。程式裡寫的模型路徑是 `/sdcard/ped_light/models/`。
4. **語音檔**：在 macOS 上用 `python tools/make_prompts.py` 產生 `board/audio/*.wav`（用 macOS 的中文語音，所以不附檔案）。

## 資料來源與致謝

- 台灣路口照片：作者自建的 Roboflow 資料集 [lawrence-yeh/traffic-sign-mos2b-zhep9](https://universe.roboflow.com/lawrence-yeh/traffic-sign-mos2b-zhep9)（CC BY 4.0）。
  - 部分畫面是影片或地圖的螢幕截圖，原始畫面的權利屬於原作者。
- 斑馬線模型另外使用了以下公開資料集（訓練用，不在這個 repo 裡）：
  - ImVisible / LYTNet（MIT，S. Yu 等，CAIP 2019）；
  - FPVCrosswalk2025（CC BY 4.0，Mendeley Data, doi:10.17632/mcr2jwk5bp.1）；
  - NTUBYOLO taiwan-street-crossing（Roboflow Universe）。

## 授權

- 程式碼：[MIT](LICENSE)。
- `dataset/` 裡的標註：[CC BY-NC 4.0](dataset/LICENSE)，可以自由用於非商業用途，請註明出處。
- 照片：依 Roboflow 資料集的 CC BY 4.0。

## 引用

請使用 [CITATION.cff](CITATION.cff)，或在 GitHub 頁面點「Cite this repository」。

## 聯絡

請在 GitHub 開 [Issue](../../issues)。

---

<a id="english"></a>
## English

**EYE** is a high-school research project from Taiwan: an **open-source** street-crossing aid for blind and low-vision pedestrians. A **CanMV K230** board reads the **pedestrian signal** (red, green, flashing green) and the **direction of the zebra crossing** in real time, and speaks the result in Mandarin.

> ⚠️ **Safety notice.** This is a research prototype with **no safety certification**. It does not replace a white cane, a guide dog, accessible pedestrian signals or human help. The design rule is "**never announce green unless sure**": silence means do not start crossing.

**What is here.**
- `board/`: MicroPython code for the K230. `ped_light_v15_bbox.py` is the current reader; `ped_light_v16_cwshadow.py` adds the crosswalk model in shadow mode.
- `tests/`: pytest tests of the pure logic.
- `tools/`: voice-prompt generation and black-box log verification.
- `dataset/`: class names, Taiwan crosswalk midline labels (near / far end) and scripts.

**Not included.**
- The photos: download them from the author's public Roboflow dataset (CC BY 4.0) with `dataset/script/download_roboflow.py`.
- The trained models: their training data includes private photos.
- The voice WAV files: generate them with `tools/make_prompts.py` on macOS.

**Licenses.** Code: MIT. Labels in `dataset/`: CC BY-NC 4.0. Photos: CC BY 4.0 (Roboflow dataset).

**Please cite** via `CITATION.cff`. Questions: GitHub Issues.
