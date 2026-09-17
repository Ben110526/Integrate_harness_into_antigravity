# Kế hoạch kỹ thuật: Bản đồ mã nguồn sơ bộ qua AST cho PreInvocation Context (v2.2)

**Ngày cập nhật:** 08/09/2026  
**Trạng thái:** Đặc tả kỹ thuật tiền triển khai hoàn chỉnh (Final Pre-Implementation Spec)  
**Phạm vi mục tiêu:** Bổ sung khả năng trích xuất vị trí code ứng viên (`candidate source hints`) bằng Python Standard Library cho hàm `_context()` tại `invocationNum == 0` trong [`plugin/codex-claude-harness/scripts/lifecycle_guard.py`](file:///Users/macbook/workspace/anti_codex_test/plugin/codex-claude-harness/scripts/lifecycle_guard.py#L950-L1001).

---

## 1. Định vị bài toán & Giới hạn phạm vi (Scope & Non-Goals)

### 1.1. Mục tiêu cốt lõi
Cung cấp một **bản đồ mã nguồn sơ bộ (preliminary candidate source hints)** để model định hướng nhanh các file và vị trí trọng yếu (`file:line`) ngay từ turn đầu tiên (`invocationNum == 0`).

### 1.2. Giới hạn phạm vi (Non-Goals)
* **Không phải bộ hiểu kiến trúc đầy đủ:** Chỉ nhận diện các dấu hiệu cú pháp ứng viên (syntactic candidate markers), không suy diễn ngữ nghĩa kiến trúc hay cây routing lồng nhau.
* **Không thay thế việc đọc source code:** AI vẫn phải tự đọc implementation, tìm call sites và chạy test kiểm chứng; bản đồ chỉ giúp gợi ý điểm bắt đầu đọc.
* **Không nạp/thực thi code dự án:** Không dùng `importlib` hay `eval/exec`.
* **Phạm vi v1:** Thuần **Python-only**, chạy single-pass in-memory, không persistent cache.

---

## 2. Ràng buộc an toàn & Phòng vệ theo chiều sâu (Safety & Untrusted Input)

Mã nguồn trong workspace là **dữ liệu không đáng tin cậy (untrusted input)**:

### 2.1. Kiểm soát Filesystem & Giảm thiểu rủi ro TOCTOU
1. **Bỏ qua Symlink hoàn toàn trong v1:**
   * Trong quá trình duyệt thư mục (`os.scandir`), kiểm tra:
     ```python
     if entry.is_symlink():
         continue
     ```
     *(Lưu ý chuẩn API Python: `os.DirEntry.is_symlink()` không nhận tham số `follow_symlinks`).*
2. **Mở file an toàn qua Directory Descriptor (`dir_fd`):**
   * Mở file tương đối qua directory descriptor trên các nền tảng hỗ trợ (POSIX `openat` thông qua `dir_fd` trong `os.open`):
     ```python
     fd = os.open(entry.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0), dir_fd=parent_fd)
     ```
   * Sau khi mở, dùng `os.fstat(fd)` xác minh file thông thường (`stat.S_ISREG(st.st_mode)`). Loại bỏ hoàn toàn FIFO, socket, device nodes.
   * **Graceful Fallback:** Trên các nền tảng hoặc môi trường không bảo đảm an toàn `dir_fd` (hoặc xảy ra lỗi OS khi kiểm tra đường dẫn cha), bỏ qua phần quét source map (`graceful skip`), giữ nguyên context manifest hiện có. Không tuyên bố hệ thống "triệt tiêu tuyệt đối TOCTOU", mà chỉ giảm thiểu rủi ro trong khả năng của hệ thống.
3. **Đọc có trần kích thước (Limit + 1 Byte) & Kế toán dung lượng:**
   * Đọc tối đa `MAX_SOURCE_FILE_BYTES + 1` bytes (`32_769` bytes).
   * Nếu dữ liệu đọc được `> 32_768` bytes, tức là file vượt quá trần 32KB $\rightarrow$ hủy bỏ (discard) ngay lập tức, không nạp vào parser. Không tin cậy đơn lẻ vào `stat().st_size`.
   * **Quy tắc kế toán byte đọc:** Toàn bộ số byte thực tế đã đọc vào bộ nhớ (bao gồm cả byte thăm dò `+1` và dung lượng của các file bị discard sau đó) **bắt buộc phải được tính cộng dồn** vào `total_bytes_scanned`.

### 2.2. Trần tài nguyên toàn cục (Global Shared Ceilings across all Roots)
Các giới hạn sau được tính **tổng cộng trên toàn bộ `roots[:4]`**, tuyệt đối không nhân lên theo số root:
* `MAX_SCANNED_ENTRIES = 150`: Tổng số directory entries duyệt qua mọi root.
* `MAX_PYTHON_FILES = 15`: Tổng số file `.py` được mở và phân tích cú pháp.
* `MAX_TOTAL_SCAN_BYTES = 262_144` (256 KB): Tổng số byte đọc tối đa trên toàn bộ các file (tính cả file bị discard).
* `MAX_SCAN_DEPTH = 3`: Độ sâu duyệt thư mục tối đa tính từ mỗi root.

### 2.3. Phòng thủ Best-Effort khi phân tích AST
* **Bảo vệ Interpreter:** Chỉ nạp chuỗi `≤ 32KB` vào `ast.parse()`.
* **Xử lý ngoại lệ có giới hạn (Bounded Best-Effort):** Bọc khối parser trong `try...except (SyntaxError, RecursionError, MemoryError, ValueError, OSError)`. Bỏ qua file lỗi trong im lặng.
* *Lưu ý kỹ thuật:* Bắt exception tầng Python không bảo vệ được 100% trong trường hợp interpreter crash ở tầng C (như segfault sâu). Giới hạn kích thước file và độ sâu duyệt là chốt chặn phòng vệ tiên quyết.

### 2.4. Chống Prompt Injection & Lọc Bí Mật (Best-Effort)
* **Loại bỏ docstring và comment:** AST visitor chỉ trích xuất tên định danh (identifiers) của class và function, cùng số dòng định nghĩa. Tuyệt đối không trích xuất chuỗi docstring hay inline comment.
* **Vệ sinh ký tự (Sanitization):** Escape và lọc toàn bộ ký tự điều khiển (`\r`, `\n`, null byte, ANSI escape, backticks) trên **cả identifier name và relative file path**.
* **Lọc bí mật tái sử dụng helpers hiện có:** Áp dụng kiểm tra secret thông qua các helper sẵn có trong [`lifecycle_guard.py:221-229`](file:///Users/macbook/workspace/anti_codex_test/plugin/codex-claude-harness/scripts/lifecycle_guard.py#L221-L229):
  ```python
  if _high_confidence_category(identifier) is not None or _has_ambiguous_secret(identifier):
      continue
  ```
  Tương tự áp dụng cho đường dẫn relative file path. Nếu nghi vấn chứa secret, bỏ qua item đó. Đây là lớp bảo vệ heuristic phòng thủ theo chiều sâu, không khẳng định loại trừ tuyệt đối mọi dạng secret.

---

## 3. Thứ tự duyệt file & Danh sách loại trừ (File Selection Policy)

### 3.1. Danh sách thư mục loại trừ cứng (Ignored Directories)
Khi duyệt thư mục, bỏ qua ngay các thư mục sau để bảo vệ ngân sách 150 entries:
```text
.git, .venv, venv, env, __pycache__, site-packages, build, dist,
.tox, .nox, .pytest_cache, .mypy_cache, node_modules, vendor, .idea, .vscode
```

### 3.2. Thứ tự ưu tiên chọn file (Priority Order)
1. **Ưu tiên 1 (Root candidates):** Các file `.py` ở ngay root (`main.py`, `app.py`, `server.py`, `manage.py`, `wsgi.py`, `asgi.py`, `run.py`).
2. **Ưu tiên 2 (Shallow target dirs - Depth 1):** Các file `.py` nằm trong các thư mục định hướng (`api/`, `models/`, `routes/`, `views/`, `controllers/`, `handlers/`, `src/`).
3. **Ưu tiên 3 (Duyệt theo chiều rộng - BFS):** Các file `.py` khác cho đến khi chạm một trong các trần: `MAX_PYTHON_FILES` (15), `MAX_SCANNED_ENTRIES` (150), hoặc `MAX_TOTAL_SCAN_BYTES` (256KB).

---

## 4. Định dạng Output & Nguyên tắc cắt gọt nguyên khối (Atomic Truncation)

### 4.1. Quy tắc hiển thị Output
* **Chỉ xuất:** `loại candidate` + `symbol (identifier)` + `đường dẫn tương đối:dòng`.
* **Không xuất URL string literals:** Trong v1, không trích xuất các chuỗi như `POST /login` hay route path strings để tránh làm sai lệch context hoặc kéo theo chuỗi không an toàn.

**Ví dụ format mẫu:**
```text
Candidate source hints: entrypoints: [src/main.py:12]; models: [User:src/models.py:5, Order:src/models.py:22]; handlers: [login_endpoint:src/api/auth.py:15].
```

### 4.2. Chia sẻ ngân sách 1024 Bytes & Cắt gọt nguyên khối
* Tổng `ephemeralMessage` luôn **≤ 1024 bytes UTF-8** (`MAX_CONTEXT_BYTES`).
* **Ưu tiên bảo toàn thông tin manifest:** Nếu các thành phần cũ (`Frameworks`, `Runtimes`, `Topology`, `Candidate checks`) đã chiếm phần lớn context và ngân sách còn lại **< 100 bytes**, bỏ qua hoàn toàn phần `source hints` để bảo vệ Candidate Checks.
* **Cắt gọt nguyên khối (Atomic Candidate Truncation):**
  * Dành sẵn 35 bytes dự phòng cho nhãn kết thúc: `... [partial: N omitted]`.
  * **Ngữ nghĩa của `N omitted`:** `N` chỉ đếm chính xác số candidate **đã được parse và tìm thấy** nhưng không đủ chỗ hiển thị. Tuyệt đối không suy diễn hay đoán số candidate trong các file chưa kịp quét.
  * Khi chuỗi chạm trần ngân sách cho phép, **bỏ nguyên vẹn candidate cuối cùng** (`[symbol:path:line]`). Tuyệt đối không cắt ngang giữa chừng chuỗi `file:line` để tránh sinh trích dẫn ảo.

---

## 5. Điểm tích hợp mã nguồn & Xử lý Repo không Manifest

### 5.1. Sửa đổi CẢ HAI điều kiện Early-Return trong `_context()`
Tại [`lifecycle_guard.py:974-984`](file:///Users/macbook/workspace/anti_codex_test/plugin/codex-claude-harness/scripts/lifecycle_guard.py#L974-L984), hiện có hai chốt chặn trả về sớm:
```python
# Điểm 1 (trước khi resolve runtime version):
if not stacks and not runtime_specs and not topology and not checks:
    return {}

# Điểm 2 (sau khi resolve runtime version):
if not stacks and not runtime_values and not topology and not checks:
    return {}
```
* **Điều chỉnh bắt buộc:** Cả hai điểm đều phải kiểm tra sự hiện diện của `source_hints`:
  ```python
  # Điểm 1:
  if not stacks and not runtime_specs and not topology and not checks and not source_hints:
      return {}

  # Điểm 2:
  if not stacks and not runtime_values and not topology and not checks and not source_hints:
      return {}
  ```
  Nhờ đó, một repository Python thuần túy chỉ có file mã nguồn (như `main.py`) mà không có manifest vẫn nhận được candidate hints mà không bị mất dữ liệu ở bất kỳ điểm nào.

---

## 6. Tiêu chí nghiệm thu (Acceptance Criteria Ledger - `AC-*`)

| ID | Tiêu chí | Cơ sở kiểm chứng |
| :--- | :--- | :--- |
| `AC-1` | **Standard Library Only** | 100% Python stdlib (`ast`, `os`, `stat`, `re`, `pathlib`). |
| `AC-2` | **Global Ceilings & Bounded Scans** | Không duyệt quá 150 entries, 15 files, 256KB tổng trên tất cả roots (tính cả byte thăm dò và file bị discard). Bỏ qua thư mục trong ignore list. |
| `AC-3` | **Mitigated TOCTOU & Symlink Safety** | Bỏ qua symlink bằng `entry.is_symlink()`; mở qua `dir_fd` trên nền tảng hỗ trợ; xác minh `stat.S_ISREG`; đọc trần `limit + 1` bytes; loại trừ FIFO/socket/device files. Graceful skip khi môi trường không an toàn. |
| `AC-4` | **Atomic Budget Sharing & Accurate Omission** | Toàn bộ `ephemeralMessage` luôn **≤ 1024 bytes UTF-8**. Khi thiếu chỗ, bỏ nguyên candidate và thêm nhãn `[partial: N omitted]` với `N` đếm chính xác candidate bị ẩn. Không đè bẹp Candidate Checks. |
| `AC-5` | **Identifier Sanitization & Secret Filtering** | Lọc bỏ docstrings/comments; escape ký tự điều khiển trên cả identifier và path; áp dụng `_high_confidence_category() is not None` và `_has_ambiguous_secret()`. |
| `AC-6` | **Zero-Manifest Python Support** | Repo chỉ có file `.py` không bị chặn bởi cả hai điều kiện early return tại dòng 974 và 983 của [`lifecycle_guard.py`](file:///Users/macbook/workspace/anti_codex_test/plugin/codex-claude-harness/scripts/lifecycle_guard.py). Bổ sung bài test gọi `_context()` hoàn chỉnh trên fixture zero-manifest. |
| `AC-7` | **Performance Benchmark & Regression Tests** | Đo latency p50/p95 dưới dạng benchmark tham khảo (ghi rõ môi trường phần cứng/OS, không áp assertion cứng trong CI). Toàn bộ [`tests/test_policy.py`](file:///Users/macbook/workspace/anti_codex_test/tests/test_policy.py) và suite [`tests/test-source.sh`](file:///Users/macbook/workspace/anti_codex_test/tests/test-source.sh) vượt qua 100%. |

---

## 7. Lộ trình triển khai v1 (Milestones)

* **Milestone 1: Bộ quét an toàn `source_mapper.py`:** Triển khai `scandir` có ignore list, bộ lọc symlink qua `entry.is_symlink()`, mở file an toàn qua `dir_fd` trên POSIX và đọc `limit + 1` với kế toán tổng byte đọc chính xác.
* **Milestone 2: AST Visitor & Bộ lọc Identifier:** Triển khai visitor trích xuất `candidate entrypoints`, `candidate models`, `candidate handlers`; loại bỏ docstrings; escape ký tự; kiểm tra qua `_high_confidence_category` và `_has_ambiguous_secret`.
* **Milestone 3: Bộ định dạng & Cắt gọt nguyên khối:** Ghép chuỗi, kiểm soát trần byte với nhãn `[partial: N omitted]`, bảo vệ ngân sách của checks.
* **Milestone 4: Tích hợp vào `_context()` & Unit Tests:** Nối vào `lifecycle_guard.py`, cập nhật cả 2 điều kiện early return (974 & 983), bổ sung test case gọi `_context()` hoàn chỉnh trên fixture zero-manifest và chạy toàn bộ regression suite.

---
*Tài liệu này là đặc tả kỹ thuật v2.2 hoàn chỉnh, giải quyết trọn vẹn các chi tiết an toàn và hành vi runtime trước khi bước vào giai đoạn cài đặt.*
