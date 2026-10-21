# EYE dataset：台灣斑馬線中線標註與類別

## 照片從哪裡來

- 照片**不在這個 repo**，在作者公開的 Roboflow Universe 資料集：
  - [lawrence-yeh/traffic-sign-mos2b-zhep9](https://universe.roboflow.com/lawrence-yeh/traffic-sign-mos2b-zhep9)，**CC BY 4.0**，標註是用 **version 1**。
- 下載方式：
  1. 註冊免費的 Roboflow 帳號；
  2. 把 API key 放進環境變數 `ROBOFLOW_API_KEY`（不要寫進程式）；
  3. 執行：

```bash
pip install roboflow
ROBOFLOW_API_KEY=... python dataset/script/download_roboflow.py --out data/roboflow_v1
```

**注意**：
- 部分照片是影片或地圖畫面的螢幕截圖，原始畫面的權利屬於原作者。請只用於研究，公開展示時要註明出處。
- 行車記錄器與機車儀表板視角的照片（檔名 `Frame_…`、`frame…`）**不在 EYE 的標註範圍內**。

## 台灣斑馬線中線標註 `crosswalk_tw/crosswalk_tw_v1.csv`

逐張人工標註，標的是「使用者面前要走的那一條斑馬線」的**中線**：
- **近端**：中線離開畫面下方的地方，或斑馬線最靠近使用者的一端；
- **遠端**：對面路緣的中央。

| 欄位 | 說明 |
|---|---|
| `split` | `train`／`valid`。依連拍分組（同一次連拍的照片不會跨切分）；**與 Roboflow 自己的切分不同** |
| `image_stem` | Roboflow v1 匯出的檔名（不含副檔名） |
| `class` | 見下表 |
| `near_x, near_y, far_x, far_y` | 0–1 的正規化座標（x 向右、y 向下）；只有 `ahead` 有值 |

| class | 意思 | train | valid |
|---|---|---|---|
| `ahead` | 使用者面前有要走的斑馬線，標近端與遠端 | 166 | 35 |
| `none` | 沒有使用者要走的斑馬線：橫在前方、在遠處、只有停止線，或機車停等區等白框（可當負樣本） | 560 | 100 |
| `unsure` | 看不清、被大量遮住、斜向離開畫面，或中線在畫面外（不要用來訓練或評估） | 240 | 45 |

**範圍**：只標「街景」照片，也就是號誌標註框高度 ≤ 畫面 25% 的照片；號誌特寫照片不在範圍內。

**判讀規則**：斑馬線條紋和車流平行。
- 使用者面前的斑馬線，看起來是一格一格往遠處堆疊的「梯子」；
- 條紋左右並排、各自指向消失點的，是橫在前方的斑馬線 → `none`。

**精度**：標註是在 10% 刻度的格線縮圖上讀出來的，座標誤差約 ±1–2% 畫面寬。用 iPhone 7 的視角換算，遠端方位約 ±1°。

**轉成 YOLO-pose 格式**（1 類、2 個關鍵點；box 是中線範圍再加中線長度的 10%）：

```bash
python dataset/script/crosswalk_csv_to_yolo.py --images data/roboflow_v1 --out data/crosswalk_tw_pose
```

## 類別名稱 `labels/`

| 檔案 | 用途 |
|---|---|
| `names_det.txt` | 號誌偵測（1 類：`ped_signal`） |
| `names_cls.txt` | 號誌顏色分類（`green`、`other`、`red`） |
| `names_crosswalk_kpt.txt` | 斑馬線關鍵點模型（1 類，關鍵點 0 = 近端、1 = 遠端） |
| `names_roboflow_ped.txt` | Roboflow 原始的行人號誌類別（`ped_red`、`ped_green`） |

## 授權

- 標註（本資料夾）：**CC BY-NC 4.0**，見 [LICENSE](LICENSE)。
- 照片：依 Roboflow 資料集的 CC BY 4.0。

## English

Hand-made zebra-crossing midline labels (near end, far end; normalised 0–1) for the street-scene photos of the Roboflow dataset [lawrence-yeh/traffic-sign-mos2b-zhep9](https://universe.roboflow.com/lawrence-yeh/traffic-sign-mos2b-zhep9) (version 1, CC BY 4.0). The photos are not in this repo.

| class | meaning | train | valid |
|---|---|---|---|
| `ahead` | the crossing in front of the user; near / far end given | 166 | 35 |
| `none` | no crossing the user would walk on (e.g. one running across the view, box markings) | 560 | 100 |
| `unsure` | not usable | 240 | 45 |

The train / valid split keeps each photo burst in one split, and differs from Roboflow's own split.

**Tools.** `script/download_roboflow.py` downloads the photos. `script/crosswalk_csv_to_yolo.py` writes a YOLO-pose dataset.

**License.** Labels: CC BY-NC 4.0.
