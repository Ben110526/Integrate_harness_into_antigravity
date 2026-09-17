# Đề xuất tối ưu harness để AI hiểu đúng và làm task lớn liền mạch

Ngày đánh giá: 06/09/2026. Source được đọc tại commit `40867f7`; worktree sạch trước khi tạo tài liệu này.

Đây là **đánh giá và kế hoạch triển khai**. Các file, schema và workflow mới bên dưới là đề xuất, chưa được cài đặt hoặc triển khai.

## 1. Hướng nên chọn

**Nên phát triển source này theo hướng một mục tiêu xuyên suốt, có milestone và bằng chứng hoàn thành.** Bạn giao kết quả cần đạt một lần; AI tự nghiên cứu, chia việc nội bộ, thực hiện, kiểm tra, sửa và tiếp tục. Milestone không đồng nghĩa với việc bạn phải gửi một prompt mới.

Source đã có nền tảng phù hợp: phân loại rủi ro, researcher, implementer, reviewer, verifier, tiêu chí `AC-*` và hook kiểm chứng. Phần cần tăng cường là **hiểu ngữ nghĩa dự án, giữ trạng thái công việc và xác nhận toàn bộ mục tiêu đã đạt**. Chỉ thêm rule hoặc thêm agent sẽ chưa giải quyết đủ ba việc này.

Thứ tự đề xuất:

1. Sửa một điểm nhận nhầm bằng chứng verification đã tái hiện; bổ sung bài đo task dài.
2. Thử workflow native của Antigravity trên một task đại diện để xác định phần runtime đã làm được.
3. Bổ sung cách giao mục tiêu, context theo task và điều kiện tự tiếp tục vào harness.
4. Chỉ xây thêm trạng thái bền vững hoặc bộ điều phối khi thử nghiệm cho thấy native còn thiếu.

Giới hạn 10 dòng trong policy hiện tại **chỉ áp dụng cho đường xử lý sửa rất nhỏ**. `COMPLEX_IMPLEMENT` đã cho phép thay đổi nhiều thành phần. Không cần nới giới hạn đó để cho phép task lớn; cần hoàn thiện cách điều phối và giữ mục tiêu. Căn cứ: [global/GEMINI.md, dòng 12–19](global/GEMINI.md).

## 2. Source hiện tại đang làm gì

Đây là plugin và lớp quy tắc chạy trong Antigravity; vòng thực thi model thuộc runtime Antigravity. Không nên suy từ việc repo chưa có scheduler riêng rằng nền tảng không hỗ trợ task dài.

```text
Yêu cầu người dùng
  → Policy định tuyến theo loại task và rủi ro
  → Skills hướng dẫn plan / implement / clarify / ship
  → Subagents thực hiện các vai trò được giao
  → Tools và MCP thu thập bằng chứng / sửa source
  → Hooks kiểm soát thao tác và nhắc verification
  → Báo cáo kết quả
```

| Thành phần | Điểm nên giữ | Căn cứ trong source |
| --- | --- | --- |
| Định tuyến | Phân loại bằng rủi ro, có đường nhẹ cho việc nhỏ | [global/GEMINI.md:9](global/GEMINI.md) |
| Hiểu yêu cầu | Thứ tự ưu tiên bằng chứng và AC có ID ổn định | [harness-plan/SKILL.md:8](plugin/codex-claude-harness/skills/harness-plan/SKILL.md) |
| Thực hiện | Sửa nguyên nhân, phân quyền sở hữu file, kiểm tra lại sau lần ghi cuối | [harness-implement/SKILL.md:9](plugin/codex-claude-harness/skills/harness-implement/SKILL.md) |
| Độc lập kiểm chứng | Reviewer đọc source; verifier chạy check; giữ mapping AC | [harness-reviewer.md:16](plugin/codex-claude-harness/agents/harness-reviewer.md), [harness-verifier.md:16](plugin/codex-claude-harness/agents/harness-verifier.md) |
| Hỏi người dùng | Chỉ hỏi quyết định quan trọng mà source không trả lời được | [harness-clarify/SKILL.md:8](plugin/codex-claude-harness/skills/harness-clarify/SKILL.md) |
| An toàn và kiểm tra | Có hook, fixture, kiểm tra policy và renderer; test local không cần model thật | [hooks.json](plugin/codex-claude-harness/hooks.json), [tests](tests), [evals/README.md:3](evals/README.md) |

## 3. Phát hiện và điểm nghẽn cần xử lý

### 3.1. P2 — hook có thể nhận một lệnh không kiểm tra source hiện tại là bằng chứng hợp lệ

**Đã tái hiện bằng fixture tạm, không sửa repository:**

1. Ghi một file `.py` trong workspace, làm phát sinh yêu cầu kiểm chứng hành vi.
2. Gọi lệnh với `Cwd` ban đầu nằm trong workspace, nhưng nội dung lệnh là `cd <outside-temp> && python -m unittest -q`.
3. Python chạy **0 test** ở thư mục ngoài workspace và trả exit code 0.
4. Hook ghi nhận behavioral evidence; lần `Stop` đầu trả `{"decision":"allow"}`.

Nguyên nhân: [verification_gate.py:1534](plugin/codex-claude-harness/scripts/verification_gate.py) xét `Cwd` ban đầu; [dòng 1559](plugin/codex-claude-harness/scripts/verification_gate.py) phân loại evidence từ command; [dòng 1738](plugin/codex-claude-harness/scripts/verification_gate.py) dùng thứ tự write/evidence để xét điều kiện dừng.

Hệ quả là hook có thể cho dừng dù chưa kiểm tra phần code vừa sửa. Đây là false positive của hook; **không phải bằng chứng rằng cả agent đã tuyên bố task thành công trong một phiên thật**.

Hướng sửa gần nhất: không dùng command có đổi thư mục hoặc test target ngoài phạm vi chưa xác minh để đóng verification debt. Thêm regression test cho tình huống trên và trường hợp hợp lệ chạy trong thư mục con. Về sau, ưu tiên bằng chứng có thư mục thực thi, test target, kết quả và revision; nhận diện `0 tests` theo runner được hỗ trợ. Exit code 0 riêng lẻ chưa chứng minh AC đã được kiểm tra.

Hai việc phải kiểm tra riêng: **phạm vi thực thi** và **test có thực sự chạy**. Probe bổ sung chạy `python -m unittest -q` ngay trong workspace không có test vẫn trả exit 0, in `Ran 0 tests` ở stderr và được gate nhận là evidence. `_handle_post` hiện không đọc output. Schema `PostToolUse` công khai chưa có `toolResult`/stdout/stderr, nên không được thiết kế dựa vào giả định trường đó luôn tồn tại. Căn cứ: [verification_gate.py:1649–1680](plugin/codex-claude-harness/scripts/verification_gate.py), [contract Hooks](https://antigravity.google/docs/hooks/).

M1 cần xác minh nguồn evidence trước: adapter/runner được hỗ trợ có thể trả nonzero khi không chạy test, hoặc tạo receipt do runner ghi với cwd, số test, kết quả và fingerprint. Chỉ parse output khi có contract đã kiểm chứng, phải xét stderr, giới hạn dữ liệu và xử lý output thiếu/truncated. Không có marker `0 tests` chưa đủ để khẳng định có test; runner chưa hỗ trợ phải được báo là chưa xác minh số test. Receipt do model tự viết cũng không chứng minh check đã chạy.

### 3.2. Các giới hạn thiết kế ảnh hưởng đến task dài

Các mục sau là khoảng trống về khả năng hoặc độ bao phủ; không tự động được xem là lỗi runtime.

| Ưu tiên | Hiện trạng có căn cứ | Ảnh hưởng và đề xuất |
| --- | --- | --- |
| Cao | Context chỉ inject ở `invocationNum == 0`, tối đa 1 KiB; gồm framework, runtime, topology, candidate checks. [lifecycle_guard.py:36, 950–1001](plugin/codex-claude-harness/scripts/lifecycle_guard.py) | Hữu ích để khởi động nhưng chưa mô tả nghiệp vụ, call chain hoặc invariants. Bổ sung bản đồ source theo task và đọc sâu đúng điểm cần sửa. |
| Cao | Plan có AC và thứ tự bước; state của verification hook lưu mốc write/evidence, không lưu mục tiêu/milestone. [harness-plan:10–18](plugin/codex-claude-harness/skills/harness-plan/SKILL.md), [verification_gate.py:1582](plugin/codex-claude-harness/scripts/verification_gate.py) | Chưa có contract phục hồi công việc dài do chính repo cung cấp. Xác minh native trước; nếu thiếu, thêm task record có version và bước tiếp theo. |
| Cao | Stop nhắc một lần rồi cho phép dừng để tránh vòng lặp. [verification_gate.py:1753–1794](plugin/codex-claude-harness/scripts/verification_gate.py) | Giữ đặc tính chống kẹt này, nhưng tách điều kiện `completed` của task khỏi quyết định cho runtime dừng. Task thiếu AC phải còn trạng thái chưa hoàn tất. |
| Cao | Case complex hiện có hai source file và ba AC; runner tiếp tục khi thiếu dòng `Harness:`. [cases.json:153–195](evals/cases.json), [run-smoke.sh:142–164](evals/run-smoke.sh) | Chưa chứng minh giữ mục tiêu qua nhiều milestone, gián đoạn và thay đổi yêu cầu. Cần eval dài đo cả chất lượng lẫn số lần người dùng phải nhắc. |
| Vừa | Policy bắt buộc nhiều vai trò cho các route phức tạp; chưa thấy ngân sách điều phối theo toàn task. [global/GEMINI.md:11–29](global/GEMINI.md) | Có khả năng tốn thời gian nếu tạo agent mới cho từng sửa nhỏ. Đo trước; giao trọn một milestone, tái sử dụng worker phù hợp và kiểm tra ở mốc ổn định. Chưa đo mức tiết kiệm. |
| Vừa | Hai policy được yêu cầu giống từng byte; test còn khóa khoảng kích thước 70–82% một baseline. [test_policy.py:17–30](tests/test_policy.py) | Khi thêm workflow, giữ một nguồn chỉnh sửa chuẩn, đồng bộ có kiểm tra; điều chỉnh budget có chủ đích. Không kéo dài hoặc thêm chữ đệm chỉ để vừa test. |

Citation grounding hiện xác minh file và dòng tồn tại, không xác minh nội dung phát biểu đúng với source. Reviewer vẫn phải kiểm tra ý nghĩa. Căn cứ: [docs/phase1-capabilities.md:109–123](docs/phase1-capabilities.md).

README còn chỉ dẫn `.\doctor.ps1` cho Windows, nhưng danh sách file hiện có `doctor.sh`; tài liệu Phase 1 hướng dẫn dùng Bash. Nên sửa chỉ dẫn này trong đợt cập nhật tài liệu để tránh gián đoạn thao tác. Căn cứ: [README.md:229–233](README.md), [docs/phase1-capabilities.md:143–149](docs/phase1-capabilities.md).

## 4. Chọn cách điều phối trước khi viết thêm framework

Tài liệu Google được đối chiếu ngày 06/09/2026 mô tả `/teamwork-preview` cho task lớn, có milestone, artifact bàn giao và verification độc lập. Workflow có bước chốt brief trước khi thực thi và yêu cầu paid plan. **Chưa kiểm chứng khả dụng hoặc tương thích với plugin trên bản cài đặt của bạn.** [Tài liệu Teamwork](https://antigravity.google/docs/teamwork).

| Trường hợp | Hướng sử dụng |
| --- | --- |
| Task thường, phạm vi rõ | Giữ các route hiện tại của harness. |
| Bug khó, cần phân tích sâu | Thử `/boost` nếu môi trường hỗ trợ. Google mô tả đây là luồng nhiều agent cho suy luận và kiểm chứng lặp. [Tài liệu Boost](https://antigravity.google/docs/boost). |
| Feature lớn, nhiều thành phần và milestone | Pilot `/teamwork-preview` trên bản sao/worktree phù hợp; ghi rõ nguồn checkout và nơi nhận kết quả. |
| Cần mở lại cuộc hội thoại | Dùng `/resume` trong CLI hoặc `agy -c` từ terminal bên ngoài phiên agent. Đây là khôi phục hội thoại; vẫn phải kiểm tra lại trạng thái source. [Tài liệu Resume](https://antigravity.google/docs/cli/commands/resume/). |

Đề xuất tích hợp của tôi: **mỗi task có một đầu mối điều phối**. Nếu native đã quản milestone, dùng harness để bổ sung contract, kiến thức repo và chất lượng evidence. Thử nghiệm xem các rule `MUST invoke` có gây tạo thêm lớp agent trùng vai trò hay không; đây là rủi ro cần kiểm chứng, chưa phải lỗi đã xác nhận.

Nếu native không khả dụng hoặc chưa đáp ứng nhu cầu, mở rộng main agent hiện tại bằng workflow `harness-run` được đề xuất ở dưới. Không cần proxy model, dịch vụ mới hoặc vòng shell tự gọi lại `agy` từ bên trong agent.

## 5. Làm sao để AI hiểu sâu và làm đúng vấn đề

### 5.1. Bắt đầu bằng kết quả quan sát được

Brief của một task cần đủ sáu điểm: vấn đề thực tế, hành vi hiện tại, hành vi mong muốn, phạm vi, ràng buộc và bằng chứng hoàn thành. AI tự tìm thông tin trong source trước, chỉ hỏi phần quan trọng còn thiếu.

Ví dụ chưa đủ rõ: “Tối ưu harness để thông minh hơn.”

Ví dụ có thể thực hiện: “Cho phép nhận một mục tiêu nhiều thành phần, tự làm qua ba milestone và tiếp tục sau gián đoạn. Hoàn tất khi mọi AC có evidence còn hiệu lực; không yêu cầu người dùng nhắc tiếp tục ở ranh giới milestone.”

Không dùng “đã sửa file”, “đã chạy test” hoặc “đã gọi reviewer” làm tiêu chí sản phẩm duy nhất. Đó là hoạt động; AC phải nói được kết quả nào thay đổi.

### 5.2. Đọc theo luồng hành vi, đến độ sâu đủ để quyết định

Researcher cần trả về bản tóm tắt có:

- Entry point → call sites → xử lý chính → đầu ra/side effect → tests.
- Những điều phải luôn đúng: quyền truy cập, dữ liệu, tương thích, thứ tự thao tác.
- Điểm nghi ngờ, bằng chứng ủng hộ/phản bác và phép kiểm tra rẻ nhất để phân biệt.
- File cần sửa, file liên quan chỉ cần đọc và rủi ro lan sang thành phần khác.

Với repo này có thể bắt đầu từ ba luồng cụ thể:

| Luồng | Đường đọc và kiểm tra |
| --- | --- |
| Cài đặt và cấu hình | `harness.config.example.json` → `scripts/render-mcp-config.js` → `install.sh` / `install.ps1` → fixture renderer/installer |
| Điều phối công việc | `global/GEMINI.md` → skill tương ứng → contract của agent → kết quả AC và eval |
| Công nhận kiểm chứng | `hooks.json` → `_event` → `_apply_event` → xử lý Stop trong `verification_gate.py` → fixture kiểm tra cả được phép và bị từ chối |

“Hiểu sâu” được đánh giá bằng việc giải thích đúng luồng, xác định tác động và dự đoán được check nào sẽ fail/pass; không đánh giá bằng số file đã đọc hay độ dài phần phân tích.

### 5.3. Dùng context theo tầng

| Tầng | Nội dung | Khi nạp |
| --- | --- | --- |
| Quy tắc nền | An toàn, quyền hạn, contract điều phối ngắn | Đầu phiên |
| Bản đồ dự án | Module, entry point, invariants, lệnh kiểm tra đã xác minh | Khởi động task; cập nhật khi vùng liên quan đổi |
| Trạng thái task | Mục tiêu, AC, quyết định, milestone hiện tại, blocker, bước tiếp theo | Bắt đầu hoặc khôi phục task |
| Source chi tiết | Định nghĩa, call sites, tests của vùng đang xử lý | Khi cần quyết định hoặc chỉnh sửa |

Bản đồ có thể nằm trong `docs/ai/project-map.md` theo convention của repo đích. Nó cần ghi phạm vi và revision đã kiểm tra. Khi mâu thuẫn, quay lại source và yêu cầu mới nhất; summary không được trở thành nguồn chân lý độc lập.

Giữ auto-context 1 KiB làm chỉ dẫn khởi động. Đo thêm lợi ích của bản đồ theo task thay vì tăng dung lượng hook để nhét cả repo. Chỉ dùng Serena hoặc tìm kiếm ngữ nghĩa khi tìm kiếm local không đủ hiệu quả; chưa cần thêm vector database.

### 5.4. Giữ yêu cầu ổn định nhưng tiếp nhận thay đổi có chủ đích

Mỗi AC có ID, kết quả cần đạt, nguồn yêu cầu và check dự kiến. Khi bạn đổi ý giữa chừng, AI cập nhật brief và đánh dấu AC bị thay thế cùng lý do; không âm thầm xóa yêu cầu khó hoặc giữ yêu cầu đã bị hủy. Sau đó chỉ lập lại phần kế hoạch và evidence bị ảnh hưởng.

## 6. Workflow liền mạch đề xuất

```text
Một brief và phạm vi đã được giao
  → Khảo sát source + xác định AC
  → Chọn 3–6 milestone có kết quả kiểm chứng được
  → Chọn milestone sẵn sàng theo phụ thuộc
  → Implement → Verify / Review → Sửa phát hiện
  → Lưu checkpoint
  → Còn milestone và không bị chặn? Tự chuyển tiếp
  → Kiểm chứng tích hợp → Đối chiếu toàn bộ AC → Bàn giao
```

Con số 3–6 là điểm khởi đầu để thử nghiệm, không phải giới hạn cứng. Một milestone nên tạo ra một hành vi hoặc năng lực có thể kiểm tra trọn vẹn. Các bước sửa hàm, thêm test hoặc cập nhật docs vẫn có thể nhỏ ở bên trong, nhưng AI quản lý chúng.

Quy tắc vận hành cần bổ sung vào plan/implement/ship:

1. Main agent giữ mục tiêu toàn task; một milestone chính đang active. Worker có thể chạy song song trên các phần độc lập của milestone đó.
2. Giao worker một phần việc hoàn chỉnh: mục tiêu, AC, file được sở hữu, dependency, check và đầu ra cần trả. Mỗi assignment phải đủ thông tin để worker mới thực hiện, không bắt buộc có lịch sử chat. Main agent dùng `invoke_subagent` theo schema thực tế của runtime.
3. Chỉ tái sử dụng worker khi main agent có `send_message`, ID còn hợp lệ và khả năng tiếp nhận đã được xác minh; nếu không, tạo worker mới từ bản bàn giao. Bảy custom worker hiện không được khai báo tool `send_message`; điều đó giới hạn khả năng chủ động gửi, không chứng minh chúng không thể nhận message từ main. Google mô tả trạng thái Idle có thể được đánh thức và giữ context, nên không coi mọi worker là “trả kết quả rồi bị đóng”. [harness-implementer.md:4–11](plugin/codex-claude-harness/agents/harness-implementer.md), [Tài liệu Subagents](https://antigravity.google/docs/subagents).
4. Đóng băng phần diff đang xét trước khi reviewer và verifier kiểm tra song song. Nếu cần sửa thêm phần đó, kết quả cũ phải được đánh giá lại.
5. Sau một milestone đạt, main agent lập tức chọn và dispatch công việc tiếp theo bằng tool trong vòng thực thi đang hoạt động. Cập nhật tiến độ phải là thông báo không kết thúc vòng hoặc artifact đã được phân loại metadata đúng; không dùng final response ở ranh giới milestone. Nếu runtime đã dừng, nội dung văn bản hoặc `next_action` trong file không tự đánh thức nó.
6. Chỉ dừng phần phụ thuộc khi có quyết định quan trọng thiếu dữ kiện, quyền thao tác chưa có, người dùng yêu cầu dừng hoặc runtime hết tài nguyên. Tiếp tục phần độc lập nếu còn hữu ích.
7. Nếu hai vòng sửa cùng một lỗi không tạo bằng chứng mới, quay lại giả thuyết và tái lập lỗi. Đây là ngưỡng chẩn đoán thử nghiệm, không phải lý do tự công nhận hoàn thành hoặc hỏi người dùng việc AI có thể tự tìm.
8. Kết thúc khi mọi AC bắt buộc có bằng chứng phù hợp với source hiện tại, các phát hiện cần sửa đã được xử lý và kiểm tra tích hợp đạt. Waiver hoặc check bị skip phải còn được hiển thị rõ.

Trạng thái tiến độ gửi cho bạn nên ngắn, ví dụ: “Milestone 2/4 đã đạt; 5/8 AC được kiểm chứng. Đang kiểm tra khả năng tiếp tục sau gián đoạn; chưa có quyết định cần bạn xử lý.”

**Điều kiện runtime cho M2:** repo hiện đăng ký Stop cho verification/grounding, chưa có gate xét milestone còn lại. Nếu model thực sự kết thúc khi debt sạch, gate hiện tại cho dừng. Nền tảng có cơ chế tiếp tục: tài liệu mô tả `Stop → decision: continue` và `PostInvocation → terminationBehavior: force_continue`. Đây là khả năng cần kiểm chứng tích hợp, không phải tính năng task-continuation đã có trong plugin. [hooks.json:39–58](plugin/codex-claude-harness/hooks.json), [contract Hooks](https://antigravity.google/docs/hooks/).

Ưu tiên giữ chuỗi tool call và dùng điều phối native. Nếu pilot cho thấy vẫn dừng sớm, mới thêm task-lifecycle guard: chỉ tiếp tục normal idle stop của task đã được giao khi còn milestone sẵn sàng; có giới hạn continuation và phát hiện không tiến bộ. Bộ đếm này không được reset chỉ vì ghi checkpoint. Tôn trọng user cancel, lỗi runtime, hết tài nguyên và quyết định đang chờ; không ép `force_continue` vô điều kiện hoặc tạo một scheduler thứ hai cạnh native.

## 7. Trạng thái bền vững: chỉ bổ sung khi cần

Repo hiện chủ động hoãn shared blackboard vì stale state, ghi đè và mất tính độc lập của review. Phần đề xuất này cần được ghi nhận là **mở rộng quyết định kiến trúc hiện tại**, có pilot và kiểm chứng trước khi bật mặc định. Căn cứ: [docs/phase1-capabilities.md:165–173](docs/phase1-capabilities.md).

Nếu artifact native đáp ứng được, dùng chúng. Nếu chưa đáp ứng, MVP tự xây chỉ cần:

```text
.harness/tasks/<task-id>/
  brief.md      # Mục tiêu, phạm vi, AC và quyết định đã chốt
  state.json    # Milestone, evidence, blocker và next_action
```

Đây là đường dẫn đề xuất, chưa được tạo. Main agent là người ghi duy nhất; worker trả kết quả cho main. Chưa cần database, message broker, event log đầy đủ hoặc dashboard.

Các trường tối thiểu của `state.json`:

| Nhóm | Dữ liệu cần giữ |
| --- | --- |
| Danh tính | `schema_version`, `task_id`, workspace chuẩn hóa, revision của brief |
| Trạng thái | `status`, `active_milestone`, milestone đã đạt và dependency |
| Quyết định | Các giả định có ảnh hưởng, quyết định đã chốt, blocker và `next_action` |
| Source | Git HEAD cùng fingerprint nội dung file thuộc phạm vi; nhận biết cả thay đổi chưa commit, file mới và file bị xóa |
| AC | ID, trạng thái, evidence liên quan; thay đổi hoặc hủy AC phải giữ dấu vết lý do |
| Evidence | Lệnh và cwd đã kiểm tra, test target, exit status, kết quả kiểm tra, fingerprint trước/sau check; đường dẫn log được giới hạn và loại thông tin nhạy cảm |
| Điều phối | Worker còn tồn tại trong phiên, vùng sở hữu file, ngân sách thực thi khi người dùng đã chỉ định |

Contract cần bảo đảm:

- Ghi atomically, khóa hữu hạn, giới hạn kích thước và từ chối path/symlink thoát workspace. JSON hỏng phải được báo là chưa khôi phục được, không tự hiểu thành “task đã xong”.
- Khi resume: đối chiếu đúng task/workspace, yêu cầu mới nhất, git status và fingerprint; khôi phục milestone; kiểm tra phần evidence đã cũ trước khi sửa tiếp. Không giả định worker ID từ phiên trước vẫn dùng được.
- HEAD đơn lẻ không đủ vì source có thể đổi mà chưa commit. MVP có thể vô hiệu hóa evidence sau mọi thay đổi source liên quan; chỉ tối ưu dependency-based invalidation khi đã có test bảo vệ.
- Trước khi bật custom checkpoint ở M3, phải tách event cập nhật metadata khỏi write/evidence của source và có regression test. Chỉ nhận dạng chính xác task-state do workflow quản lý, kiểm tra schema, workspace và đường dẫn; không miễn trừ cả `.harness/**` hoặc mọi `.json`. Script/config trong cùng cây vẫn phải tạo debt; sửa brief/AC phải làm evidence liên quan được xét lại.
- Chỉ đổi `requiresBehavioral` thành `false` chưa đủ: mutation vẫn xóa `lastEvidenceStep` và tạo generic debt. Metadata hợp lệ phải có cách xử lý riêng để không thay các mốc evidence của source không đổi. Ghi từ terminal không xác định được phạm vi vẫn phải xử lý thận trọng; không bỏ qua cả command chain có sửa source vì nó cũng ghi checkpoint.
- Reviewer nhận AC, contract, source và diff thực tế; kết luận của implementer hoặc dòng `verified` trong JSON không thay thế review độc lập.
- Hết quota, user cancel hoặc cần quyết định: lưu trạng thái còn dang dở và bước tiếp theo. Runtime dừng không đồng nghĩa task `completed`.

Probe checkpoint đã xác nhận: ghi source → test pass → ghi `state.json` bằng file-write thông thường làm Stop `continue`; không ghi thêm thì lần sau `allow`. Mỗi checkpoint mới reset `gateRetries=0`, nên nếu agent lại ghi checkpoint trước mỗi Stop, nhắc verification có thể lặp. Đây là rủi ro tích hợp trước M3, không phải deadlock vô điều kiện đang tồn tại. Nhánh `IsArtifact=True` hiện được hook bỏ qua, nhưng không được tùy tiện gắn cờ đó cho file workspace để né kiểm tra. Căn cứ: [verification_gate.py:736–755](plugin/codex-claude-harness/scripts/verification_gate.py), [dòng 1582–1622](plugin/codex-claude-harness/scripts/verification_gate.py), [dòng 1753–1794](plugin/codex-claude-harness/scripts/verification_gate.py).

Kinh nghiệm về việc để lại tiến độ có cấu trúc và kiểm chứng kết quả xuyên context window cũng được trình bày trong [nghiên cứu kỹ thuật của Anthropic về harness cho agent chạy dài](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents). Áp dụng ở đây là đề xuất thiết kế cho repo này, chưa phải kết quả benchmark. Không đưa thao tác tự commit/reset từ workflow khác vào quyền mặc định của harness.

## 8. Kế hoạch triển khai theo milestone

Đây có thể là **một task triển khai duy nhất**. Các milestone dưới đây là thứ tự nội bộ để AI tự thực hiện và kiểm chứng.

| Milestone | Công việc và file dự kiến | Điều kiện đạt |
| --- | --- | --- |
| M1 — Làm chắc bằng chứng và baseline | Sửa `plugin/codex-claude-harness/scripts/verification_gate.py`; thêm regression vào `tests/test_verification_gate.py`. Xác minh adapter/runner cho no-tests; chốt contract metadata trước M3. Xác định task và tiêu chí pilot native. | Phân biệt check ngoài workspace, chạy 0 test và check hợp lệ. Không phụ thuộc `toolResult` chưa được cam kết. Có baseline chất lượng và số lần phải nhắc tiếp tục. |
| M2 — Giao mục tiêu và tự tiếp tục | Mở rộng `harness-plan`, `harness-implement`, `harness-ship`; thêm `skills/harness-run/SKILL.md` nếu cần. Giữ policy ngắn, đồng bộ hai bản; xác minh khả năng main/worker và thử dừng sớm. Chỉ thêm lifecycle guard hữu hạn nếu pilot cần. | Một brief tạo được AC/milestone và dispatch tiếp mà không final sớm; có fallback worker mới. Policy nằm trong budget, plan-only vẫn chỉ lập kế hoạch; cancellation được tôn trọng. |
| M3 — Context và phục hồi | Ưu tiên artifact native. Nếu cần custom: thêm `scripts/task_state.py`, `schemas/task-state.schema.json`, `tests/test_task_state.py`; cập nhật phân loại metadata trong `verification_gate.py` và test trước khi bật checkpoint; nối hint vào `lifecycle_guard.py`. | Checkpoint hợp lệ không xóa evidence source hoặc reset bộ đếm continuation; source/config vẫn tạo debt. Resume đúng milestone, phát hiện source/brief đổi, xử lý state hỏng và ghi đồng thời. |
| M4 — Eval trọn workflow và tài liệu | Thêm fixture nhiều milestone vào `evals/fixtures/`, case vào `evals/cases.json`; cập nhật runner/test eval, README và architecture/Phase 1. | Task đạt đủ AC, giữ thay đổi có sẵn, vượt bài interrupt/resume và không tăng false completion. Ghi rõ khả năng native đã thử và phần còn hạn chế. |

Phụ thuộc chính: M1 → M2 → M3 → M4; thiết kế bài eval có thể làm sớm để các milestone có tiêu chí rõ. Nếu pilot native đáp ứng phần phục hồi, thu hẹp M3 thành adapter/context và kiểm chứng tích hợp; không xây lại state engine.

Các ràng buộc triển khai cần nhớ:

- Cấu hình version 1 hiện chỉ nhận `version` và `mcp`; không tự thêm `execution` hoặc `memory` vào `harness.config.json`. Nếu cần cấu hình mới, dùng schema riêng hoặc thiết kế migration có chủ đích. Căn cứ: [render-mcp-config.js:108–112](scripts/render-mcp-config.js), [harness.config.schema.json:5–12](schemas/harness.config.schema.json).
- Policy hiện là **7.335 byte**, trần nguyên theo test là **7.673 byte**, còn **338 byte**; hai bản đang giống nhau. Giữ routing ngắn trong policy, để chi tiết milestone/resume trong skill được nạp khi cần; không xóa ràng buộc an toàn hoặc tự tăng baseline chỉ để qua CI. Chỉ thay budget khi có lý do thiết kế và phép đo tương ứng. Skill mới phải được bổ sung vào kiểm tra inventory hiện có. Căn cứ: [test_policy.py:17–30](tests/test_policy.py).
- Giữ một lớp điều phối; không chồng native orchestrator với một cây custom agent tương tự mà chưa đo lợi ích.
- Dùng hook để nạp hint, ghi nhận và nhắc kiểm chứng. Đừng biến Stop thành vòng gọi model vô hạn hoặc ép tiếp tục sau user cancel.
- Tài liệu và file trạng thái không tự tạo khả năng chạy khi app đóng, vượt context/quota hoặc tự khởi động lại. Những việc đó phụ thuộc tính năng thực tế của runtime.

## 9. Cách kiểm tra rằng việc tối ưu có ích

Đo **kết quả của cả task** trước số lượng tool call. Bộ eval nên có các tình huống:

| Tình huống | Điều cần chứng minh |
| --- | --- |
| Feature có 3 milestone phụ thuộc | Một yêu cầu ban đầu dẫn đến đủ hành vi mong muốn; không cần nhắc ở từng milestone |
| Dừng giữa M2 rồi mở lại | Giữ mục tiêu/AC, nhận ra phần đang làm và không làm lại phần đã kiểm chứng còn hiệu lực |
| Người dùng sửa thêm source giữa phiên | Giữ thay đổi của người dùng; evidence bị ảnh hưởng trở thành stale |
| Người dùng đổi một yêu cầu | Cập nhật đúng brief, AC và dependency; không làm theo yêu cầu cũ đã bị thay thế |
| Chạy check ngoài workspace hoặc 0 test | Không công nhận là kiểm chứng hành vi của phần đã sửa |
| Test pass → checkpoint → Stop | Checkpoint hợp lệ giữ evidence source; metadata hỏng không được công nhận; script/config dưới `.harness/` vẫn tạo debt |
| Milestone đạt nhưng model muốn final sớm | Dispatch được milestone kế tiếp hoặc guard hữu hạn tiếp tục đúng; không force-continue sau cancel |
| Main thiếu `send_message` hoặc worker ID hết hiệu lực | Worker mới tiếp nhận assignment đủ thông tin, không phụ thuộc lịch sử chat |
| Một AC fail dù suite khác pass | Không đánh dấu hoàn tất task |
| Worker fail, state hỏng hoặc hết ngân sách | Bàn giao được tình trạng dang dở và next action; không giả pass hoặc lặp vô hạn |
| Task rất nhỏ và task plan-only | Đường nhẹ vẫn nhẹ; yêu cầu chỉ lập plan không bị chuyển thành sửa sản phẩm |

Chỉ số nên ghi: tỷ lệ AC được kiểm chứng, số lần người dùng phải nhắc `continue`, số câu hỏi quyết định thực sự cần thiết, tỷ lệ resume đúng, thời gian hoàn tất, vòng sửa không có tiến bộ và token usage nếu runtime cung cấp. Đếm permission prompt riêng để không “tối ưu” bằng cách bỏ kiểm soát quyền.

So sánh baseline/candidate trên cùng model, fixture, quyền và môi trường; lặp ít nhất ba lần cho pilot, báo median/range cùng từng lỗi. Mục tiêu ban đầu: **không cần nhắc tiếp tục ở ranh giới milestone trên các task có brief đầy đủ, đồng thời không giảm tỷ lệ AC pass hoặc tăng false completion**. Ba lần chỉ là pilot, chưa chứng minh độ tin cậy tổng quát.

`quota_benchmark.py` hiện đo các case read-only được bật benchmark; nó không tự bao phủ task triển khai dài. Cần mở rộng phép đo phù hợp, không lấy kết quả lookup làm bằng chứng workflow lớn đã tốt hơn. Căn cứ: [evals/README.md:83–109](evals/README.md).

## 10. Prompt mẫu để giao một task lớn

Mẫu dưới đây dùng sau khi bạn quyết định triển khai. `/harness-run` trong kế hoạch là skill đề xuất, hiện chưa tồn tại; không cần gõ lệnh đó để dùng mẫu này.

```text
Hãy triển khai khả năng xử lý task lớn liền mạch cho harness này,
theo kế hoạch trong DE_XUAT_TOI_UU_AI_WORKFLOW.md.

Mục tiêu: nhận một brief nhiều thành phần, tự lập và thực hiện milestone,
giữ trạng thái qua gián đoạn và chỉ báo hoàn tất khi mọi AC bắt buộc
có bằng chứng còn hiệu lực.

Trước khi sửa, đọc instructions, git state, contract, call sites và tests;
đối chiếu khả năng native để chọn phần thực sự cần bổ sung.
Ưu tiên tái sử dụng kiến trúc và công cụ đang có.

Hãy tự quản lý M1–M4 như một task xuyên suốt: nghiên cứu, lập plan,
implement, review/verify độc lập, sửa phát hiện và tự chuyển milestone.
Tôi không cần gửi một prompt mới cho từng bước nội bộ.

AC-1: Check ngoài phạm vi hoặc không thực sự chạy test không được
      đóng verification debt của source đã sửa.
AC-2: Brief, AC và milestone tiếp theo được giữ đúng khi resume.
AC-3: Source thay đổi làm evidence liên quan mất hiệu lực;
      thay đổi sẵn có của người dùng được bảo toàn.
AC-4: Task mẫu ba milestone hoàn tất mà không cần nhắc continue
      giữa các milestone, khi không có blocker hay quyết định còn thiếu.
AC-5: Task nhỏ và plan-only giữ đúng hành vi hiện tại;
      mọi check bị skip hoặc fail được báo trung thực.

Chỉ hỏi tôi khi có quyết định quan trọng chưa thể xác định từ source
hoặc thao tác cần thêm quyền. Tiếp tục phần độc lập trong lúc chờ.
Nếu phải dừng, để lại checkpoint và bước tiếp theo rõ ràng.

Phạm vi được giao: thay đổi local trong repository, test và tài liệu
cần thiết. Chưa bao gồm commit/push, cài plugin vào môi trường thật
hoặc chạy model benchmark tiêu thụ quota. Chuẩn bị phần đó để tôi
xem và cấp quyền khi cần; không chặn các bước local độc lập.

Bàn giao: kết quả theo từng AC, file thay đổi, lệnh kiểm tra và kết quả,
các phần native đã kiểm chứng, hạn chế còn lại và cách dùng workflow.
```

## 11. Phạm vi kiểm chứng của lần đánh giá này

Đã đọc policy, các skill và agent cốt lõi, lifecycle/verification hooks, cấu hình và renderer, phần liên quan của installer, tài liệu, CI và eval. Đây là review tập trung vào tính đúng đắn và khả năng làm task dài; không phải audit toàn bộ mọi nhánh installer hoặc bảo mật toàn hệ thống.

| Lệnh đã chạy | Kết quả |
| --- | --- |
| `python3 -m unittest -q tests/test_policy.py` | 7 pass |
| `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_lifecycle_guard.py` | 46 pass, 1 Windows skip |
| `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_verification_gate.py` | 87 pass, 2 Windows skip |
| `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_evals.py` | 14 pass |
| `node --test tests/test-render-mcp-config.js` | 15 pass |

Tổng: **172 test case, 169 pass, 3 skip theo nền tảng, 0 fail trong suite hiện có**. Probe ở mục 3.1 chạy riêng đã xác nhận false positive mà suite hiện tại chưa bắt. Vì vậy, test suite pass không đồng nghĩa source không còn lỗi.

Chưa chạy live Antigravity, `/teamwork-preview`, `/boost`, smoke/quota benchmark dùng model thật, installer, doctor hoặc toàn bộ CI đa nền tảng. Test eval local dùng fake `agy`; không chứng minh cách model thật điều phối subagent. Phiên review này dùng subagent của môi trường hiện tại vì không có tool Antigravity `invoke_subagent`.

Sản phẩm của lần đánh giá là file Markdown này. Việc sửa hook và triển khai workflow là công việc tiếp theo được đề xuất, chưa thực hiện.

## 12. Đối chiếu năm rủi ro được phản biện

Cập nhật ngày 06/09/2026. Giữ số thứ tự theo danh sách phản biện; mức ưu tiên bên dưới dựa trên điều kiện thực tế, không giữ nguyên nhãn CRITICAL khi chưa có căn cứ.

| Mục | Kết luận | Điều chỉnh kế hoạch |
| --- | --- | --- |
| 1. Checkpoint làm kẹt Stop | **Đúng về debt; HIGH khi triển khai M3 thiếu xử lý, không phải CRITICAL vô điều kiện.** Ghi `.json` thông thường làm mất evidence; Stop nhắc một lần. Chỉ lặp khi có ghi mới làm reset retry. Nhóm static cũng không được miễn toàn bộ debt. | Tách metadata chính xác khỏi source debt trước khi bật M3. Không miễn wildcard `.harness/**`; không thêm toàn bộ `.json` vào static. |
| 2. Tự chuyển milestone | **Đúng về khoảng trống điều phối trong repo.** Không đủ căn cứ nói mọi progress text đều kết thúc phiên hoặc nền tảng hoàn toàn thiếu cơ chế runtime. | Tool dispatch tiếp trong vòng đang chạy; tách progress khỏi final. Nếu cần, dùng lifecycle guard hữu hạn và kiểm chứng trên CLI thật. |
| 3. Subagent không có `send_message` | **Đúng về danh sách tool; kết luận run-to-completion rồi bị đóng là không đúng với tài liệu native hiện tại.** Main gửi và worker nhận là hai khả năng khác nhau. | Assignment luôn tự đủ thông tin; reuse là tối ưu có điều kiện, worker mới là fallback. Không tự thêm tool giao tiếp cho cả bảy worker. |
| 4. Budget policy | **Đúng; MEDIUM.** 7.335/7.673 byte, còn 338 byte. Đây là rủi ro của thay đổi M2, không phải CI hiện đã fail. | Đưa chi tiết vào skills; giữ mirror, contract và budget, kiểm tra byte sau sửa. |
| 5. `0 tests` và `toolResult` | **Đúng về false positive; MEDIUM.** Probe ngay trong workspace xác nhận exit 0 dù 0 test vẫn được nhận. `toolResult` không phải đầu vào công khai được cam kết. | Xác minh adapter/runner hoặc receipt thực; không chỉ thêm regex vào command hay parse một trường có thể không tồn tại. |

Kiểm chứng bổ sung chỉ dùng fixture tạm và hook hiện tại: checkpoint sau 1 test pass; Stop lần đầu/lần hai; ba chu kỳ checkpoint mới; giả lập phân loại JSON thành static trong bộ nhớ; zero-tests trong workspace; payload không có `toolResult` và payload tổng hợp có trường đó. Payload tổng hợp chỉ chứng minh code bỏ qua trường, không chứng minh CLI thật gửi nó. Không sửa mã nguồn hay chạy lại suite rộng; đã kiểm tra byte/mirror, đối chiếu tài liệu Google và cập nhật bản kế hoạch.
