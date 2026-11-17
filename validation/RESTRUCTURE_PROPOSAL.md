# Đề xuất tái cấu trúc pipeline validation

Trạng thái: **đang làm** (bước 0–3 xong cho unit 02; xem README.md). Branch `validation-restructure` tách từ `main` ngay sau khi
bộ validation hiện tại (`af1aa7b`, import từ branch `validation` @ `b9f5894`) được đưa vào `main`.

## 1. Hiện trạng (đọc toàn bộ 24 notebook + `_shared/validation_utils.py`)

Điểm mạnh, giữ nguyên:

- Phương pháp đo đã chốt và viết rõ trong `VALIDATION_METHODOLOGY.md`: truth = annotation của
  chính record sau khi chuẩn hóa tên; mẫu số `R ∩ truth`; đúng khi IoU ≥ 0.90 hoặc hai biên
  lệch ≤ 6 bp; miễn codon check cho gene mà reference không codon-clean; engine bị ép chạy.
- Notebook gọi code tool thật qua `_shared/validation_utils.py`, không chép lại logic.
- Toàn bộ 63 import từ `app.src` trong các notebook vẫn tồn tại trên `main` hôm nay.

Điểm yếu cần sửa:

| # | Vấn đề | Bằng chứng |
|---|---|---|
| 1 | Không chạy lại được bằng một lệnh. Mỗi notebook chạy tay, `RUN_FULL` tự bật, output trộn với notebook. | 24 notebook, 10 cái không có `RUN_FULL`, 7 cái chưa từng được execute (không có output). |
| 2 | Số liệu "chính thức" nằm rải trong markdown của notebook, không có một file tổng kết máy đọc được. | Headline 99.75 / 99.83 / 99.80 chỉ có trong `NOTEBOOK_MANIFEST.tsv` và cell markdown. |
| 3 | Helper trôi ra khỏi `_shared`: 7 notebook tự định nghĩa 3–8 hàm riêng (unit 05, 07). Ba notebook `03_alias_suggestion/reconstruction_*` không dùng `_shared` chút nào. | Cột `own_defs` khi quét notebook: liftoff 4, lifton 4, vapid 7–8, gatu 3, ablation 4. |
| 4 | Ba notebook `02_lifting_accuracy/*_accuracy.ipynb` là một notebook nhân ba theo virus. | Cùng cấu trúc cell, khác `REF`/`QUERY`. |
| 5 | Kết quả cũ chiếm 7.7 MB trong 13 MB: `_archive_tblastn_breakdown` (158 file, có cả PDF/HTML report), `_archive_ped` (48 file). README đã nói đây không phải nguồn số chính thức. | `git ls-tree -l validation -- validation`. |
| 6 | Unit 04 (minimap vs tblastn) gọi `app/src/annotation/extractor.py`, file này hiện crash (`rescue_start_codon` trả 4 giá trị, code unpack 3). | `docs/CODE_REVIEW.md` P1-28. |
| 7 | Notebook ghi cùng một output dir, nên không so được "lần chạy trước" với "lần chạy này". Không ghi phiên bản tool, BLAST, commit đang chạy. | Không file metadata nào trong `outputs/`. |
| 8 | Kiến trúc hiện tại chỉ biết một reference; multi-reference (`run_pipeline_multiref`) chưa có chỗ đứng. | `load_reference_bundle(ref_path)` nhận một path. |
| 9 | Số đơn vị dính "tên theo giai đoạn": README unit 01 ghi `# 02`, unit 03 ghi `# 07`, unit 04 ghi `# 01`, unit 10 ghi `# 03`. | README của từng unit. |

## 2. Mục tiêu của bản tái cấu trúc

1. Một lệnh chạy lại toàn bộ, ra một thư mục kết quả có đóng dấu commit + phiên bản.
2. Notebook chỉ là **giao diện xem và diễn giải**; mọi tính toán nằm trong module Python có test.
3. Thêm engine mới hoặc reference mới chỉ là thêm một cấu hình, không thêm notebook.
4. Số liệu headline sinh ra từ máy, đọc được bởi máy (`summary.json`), docs trích từ đó.

## 3. Cấu trúc đề xuất

```
validation/                          # đã chuyển ra khỏi app/: không phải code tool, không đóng gói
  README.md                          # cách chạy, bản đồ câu hỏi -> unit
  METHODOLOGY.md                     # giữ nguyên nội dung hiện tại
  configs/
    datasets.yaml                    # virus -> ref(s), query set, feature level, R
    engines.yaml                     # tblastn (production), minimap2, liftoff, lifton, gatu, vapid
    runs/                            # mỗi lần chạy = 1 file: dataset x engine x tham số
  valkit/                            # thư viện Python có test (thay _shared/validation_utils.py)
    datasets.py                      # load reference bundle (1 hoặc N reference), truth, R
    truth.py                         # parse_truth, dedupe_truth_by_name, R ∩ truth
    metrics.py                       # iou, coord-correct, buckets exact/coord_only/failed
    engines/                         # một adapter / engine, cùng giao diện: lift(ref_bundle, record) -> rows
      viralift.py                    # gọi lift_all_tblastn / run_pipeline / run_pipeline_multiref
      minimap.py                     # thay thế app/src/alignment + annotation (sửa bug unpack)
      liftoff.py, lifton.py, gatu.py, vapid.py   # đọc output tool ngoài -> rows
    report.py                        # per_gene, overall, failure adjudication, figure
    runner.py                        # thực thi một run config, ghi outputs/<run_id>/
  units/                             # notebook mỏng, chỉ đọc outputs/<run_id>/ và diễn giải
    01_dataset.ipynb
    02_alias_coverage.ipynb
    03_lifting_accuracy.ipynb        # một notebook, tham số virus (papermill)
    04_engine_comparison.ipynb
    05_tool_comparison.ipynb
    06_ablation_runtime.ipynb
    07_failure_attribution.ipynb
    08_recovery_unannotated.ipynb
    09_pipeline_end_to_end.ipynb
    10_multi_reference.ipynb         # mới: best-reference-per-record vs single reference
  tests/                             # pytest cho valkit: metric, truth filter, adapter parsing
  outputs/                           # git-ignored, trừ outputs/latest/summary.json + figures
    <run_id>/                        # run_id = YYYYMMDD_<commit>_<config>
      manifest.json                  # commit, python, biopython, tblastn version, tham số
      per_prediction.tsv, per_gene.tsv, overall.tsv, failure_adjudication.tsv
  archive/                           # _archive_* chuyển sang đây, hoặc xóa khỏi git, giữ tag
```

Lý do đổi từng chỗ:

- **`valkit/` thay `_shared/validation_utils.py`**: 731 dòng một file, 25 hàm, không test. Tách
  theo trách nhiệm và viết test cho `metrics.py` và `truth.py` (những chỗ quyết định con số).
- **Adapter engine**: unit 04 và 05 hiện mỗi notebook tự parse output của tool ngoài. Một giao
  diện chung `lift(...) -> rows` làm cho so sánh N engine là một vòng lặp, và là chỗ cắm
  `run_pipeline_multiref` sau này.
- **`configs/datasets.yaml`**: khai báo reference dạng danh sách. Single reference là danh sách
  một phần tử. Khi engine hỗ trợ 2+ reference, chỉ thêm phần tử.
- **`runner.py` + `outputs/<run_id>/`**: chạy lại không ghi đè kết quả cũ, so sánh hai run bằng
  `diff` hoặc một notebook so sánh. Cùng tinh thần `tools/regression_corpus.py`.
- **Notebook mỏng + papermill**: `03_lifting_accuracy.ipynb` nhận `virus` làm tham số, thay ba
  bản chép. Execute bằng `papermill` hoặc `jupyter nbconvert --execute` trong CI local.
- **Ra khỏi `app/`**: `pyproject.toml` đã phải exclude `app.validation*`; để ở root tránh đóng
  gói nhầm và tách rõ "tool" với "đánh giá tool".

## 4. Cách làm theo từng bước (mỗi bước một PR nhỏ, chạy lại được)

| Bước | Việc | Kết quả kiểm chứng |
|---|---|---|
| 0 | Chạy lại nguyên trạng 24 notebook trên `main` hôm nay bằng `nbconvert --execute`, ghi số ra `baseline_<commit>.json`. Notebook nào không chạy được thì ghi lý do. | Biết cái gì còn sống trước khi đụng vào. |
| 1 | Tạo `validation/valkit/` bằng cách **chuyển nguyên** hàm từ `_shared/validation_utils.py`, chưa đổi logic. Viết test cho `iou`, coord-correct, `R ∩ truth`, `dedupe_truth_by_name`, buckets. | Số từ bước 0 không đổi. |
| 2 | Viết `datasets.yaml`, `engines.yaml`, `runner.py` cho engine `viralift` (tblastn). Chạy ra `outputs/<run_id>/` cho 3 virus. | `overall.tsv` khớp 99.75 / 99.83 / 99.80 (hoặc khớp bước 0 nếu đã lệch). |
| 3 | Gộp ba notebook accuracy thành một notebook tham số hóa, đọc từ `outputs/`. | Cùng bảng, cùng hình. |
| 4 | Adapter cho liftoff, lifton, gatu, vapid; gom 7 notebook unit 05 thành một. Hàm riêng trong notebook chuyển hết vào adapter. | Bảng so sánh tái tạo được số trong `CONSISTENCY_unit05.md`. |
| 5 | Adapter minimap2: sửa `annotation/extractor.py` (unpack 4 giá trị) và `sam_lifter` (bỏ qua strand), hoặc viết lại gọn trong `valkit/engines/minimap.py` rồi xóa `app/src/alignment`, `app/src/annotation`. | Unit 04 chạy lại được lần đầu kể từ 2026-05. |
| 6 | Ablation, failure attribution, recovery, end-to-end: chuyển sang đọc `outputs/`, bỏ hàm riêng. | Số không đổi so với bước 0. |
| 7 | `10_multi_reference.ipynb`: với PEDV (2 ref có sẵn) chạy single-ref từng ref vs `run_pipeline_multiref`, đo bằng cùng metric. | Bảng mới, chuẩn bị cho task multi-reference. |
| 8 | Dọn: `_archive_*` ra `validation/archive/` hoặc xóa và gắn tag `validation-archive-2026-07`; sửa số thứ tự README; `docs/` trích số từ `summary.json`. | Repo nhẹ hơn ~8 MB, README không còn lệch số unit. |

Thứ tự 0 → 1 → 2 → 3 là bắt buộc trước khi đụng engine khác, vì bước 1–2 là chỗ bảo đảm
con số không đổi.

## 5. Quyết định cần bạn chốt trước khi bắt đầu

1. **Vị trí**: `validation/` ở root (đề xuất) hay giữ `validation/units/`.
2. **Archive**: giữ trong git (7.7 MB) hay xóa và giữ bằng tag.
3. **Output nào được commit**: đề xuất chỉ `outputs/latest/summary.json` + hình PNG dùng trong
   docs; TSV chi tiết git-ignore, tái tạo bằng runner.
4. **Công cụ chạy notebook**: `papermill` (thêm dependency) hay `jupyter nbconvert --execute`
   (đã có trong extra `validation`).
5. **Unit 04 minimap**: sửa code cũ trong `app/src` hay viết adapter mới rồi xóa code cũ.
6. **Tên engine production trong bảng**: "ViraLift (tblastn)" hay thêm cả chế độ "ViraLift
   multi-ref" ngay từ bước 2.
