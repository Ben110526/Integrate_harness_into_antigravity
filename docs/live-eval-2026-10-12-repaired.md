# Eval sau sửa protocol và native MCP — 12/10/2026

Bản cuối `8603d7...` đã cài đạt **8/8 nhóm hành vi độc lập**, public tests và completion/response/scope checks đều đạt qua bốn lượt cùng conversation. Thời gian **1.103,432 giây (18,391 phút)**, total token cuối **551.994**: giảm **49,49% thời gian và 75,06% token** so với lần tối ưu trước. MCP browser thật đạt với bốn lần `Ask`, không gợi ý tool cho model; operator đã kiểm tra readiness và model thiếu Harness line, nên không coi đây là bằng chứng cold-start hoặc workflow compliance. Các lần lỗi/dừng trước vẫn giữ riêng; không chấm lại kết quả lịch sử.

Artifact đối chiếu: [kết quả đã lọc](../evals/results/2026-10-12-repaired.json). Đối chứng gồm [baseline](live-eval-2026-10-12.md) và [lần tối ưu trước](live-eval-2026-10-12-optimized.md).

## Nguyên nhân đã xác nhận và sửa đổi

**Response tổng hợp khác response cuối.** Probe Stop riêng trước đó đã quan sát hai `agent_response` riêng, còn terminal result ghép cả hai. Vì vậy, đếm mọi `HARNESS_RESULT` trong terminal aggregate có thể báo trùng dù mỗi response riêng chỉ có một envelope. Probe này không xác định được nguồn claim trùng trong bài bốn lượt cũ vì raw response-step evidence của lần đó không được giữ.

Runner bổ sung chế độ `process-events` (nay là mặc định; chế độ `process` cũ vẫn có thể chọn): vẫn gửi mỗi yêu cầu tự nhiên bằng một process `agy -p`, giữ cùng conversation qua bốn lượt, nhưng đọc public `stream-json`. Runner dựng text theo `step_index`, yêu cầu response cuối `DONE`, đối chiếu nó với hậu tố terminal aggregate và chấm response cuối đó. Nhiều envelope trong chính response cuối vẫn bị từ chối; aggregate và final claim count được ghi riêng. Không chọn tùy tiện marker cuối từ aggregate và không chấm lại lần chạy cũ. Bài waiting list còn yêu cầu envelope hiện diện và `status: complete`; partial/blocked vẫn được giữ là kết quả chưa hoàn thành, dù có tiêu chí hành vi đạt.

Parser hỗ trợ các trạng thái public `ACTIVE`, `DONE`, `ERROR`; lỗi tool có thể được response `DONE` sau đó xử lý, nhưng response cuối còn lỗi không được chấm thành công. Runtime cũng có thể chuyển cùng step từ tool `ACTIVE` sang subagent `DONE` với structured metadata, hoặc refresh metadata không có text sau khi step đã hoàn thành. Parser chỉ chấp nhận các trường hợp hẹp đó, giữ tool identity một lần; repeated text completion và tool/user/subagent action sau final vẫn bị từ chối. Không có fallback đoán loại step bị thiếu.

Observer cuối còn từ chối tool/subagent `ACTIVE` chưa hoàn thành dù xuất hiện trước response cuối, và từ chối step `ERROR` sau response cuối. Diagnostic từ chế độ legacy được lọc theo whitelist thay vì sao chép payload tùy ý. Nếu command parameters đến sau tool name, observer dùng retained tool identity để phân loại mà không lưu command text vào summary. Đây là sửa runner, không đổi quyền hoặc điều kiện gate của harness đã cài.

Policy và leaf agents quy định chỉ main phát envelope cuối; Stop correction thay thế response trước. Gate cung cấp bounded repair context gồm current-user step, evidence floor và tối đa tám bước kiểm tra thành công hợp lệ cho mỗi loại behavioral/static. Không đưa nội dung lệnh, đường dẫn hoặc yêu cầu vào hint. Step cũ hoặc bị lần chạy lỗi sau đó thay thế không được đề xuất. Đây chỉ là ứng viên: liên quan tới AC và delivery review hiện hành vẫn bắt buộc; không hạ điều kiện hoàn thành.

**ID quan sát sớm, không phải claim hoàn thành.** `PreInvocation` bổ sung một ephemeral advisory riêng, tối đa 1.024 byte, trên mỗi invocation hợp lệ. Current-user step lấy từ bounded validated transcript, không đoán từ `initialNumSteps`. Chỉ đưa số current-user/evidence-floor/check IDs; bỏ hint khi bằng chứng user thiếu, truncated, duplicate, sai thứ tự hoặc không an toàn. State contract/check của lượt trước không cấp check candidates cho lượt mới. Candidate filter dùng chung với Stop để loại stale/later-failed evidence và giữ verified ordered-chain; Stop còn bắt buộc check đứng trước response được chấm.

Advisory dành cho **main** khi non-inline contract/reporting vốn đã cần, không yêu cầu đăng ký contract cho read-only/inline. Nó không ghi state, không chứa request/command text, đường dẫn hoặc credentials; AC relevance và delivery review hiện hành vẫn bắt buộc. MCP/stack/runtime discovery vẫn chỉ ở invocation đầu. Source có hỗ trợ ephemeral injection không chứng minh client live đã nhận hint hoặc nhanh hơn; `Ask` và completion gates giữ nguyên.

**Native dispatcher khác schema server tool.** Cache JSON chứng minh có metadata, không đăng ký native invoker hoặc chứng minh kết nối sống. Policy kiểm tra exposed definition trước, chỉ dùng tên/argument schema thực sự được client công bố. `browser_navigate` trong schema server không tự trở thành top-level alias. `unknown tool` được phân loại là dispatch failure trước `Ask`; model dừng thay vì đoán alias hay tạo client thay thế. Quyền mặc định `Ask`, consent và xử lý từ chối được giữ nguyên.

**Nguồn workflow dư thừa.** Step workflow cũ yêu cầu reviewer trước edits trong khi route normal đã chỉ định verifier scope → implementer → verifier delivery; hai câu có thể khiến model gọi thêm reviewer. Policy thống nhất independent scope review theo route. Documenter vẫn bắt buộc cho tài liệu public-consumer API/operator và release deliverables cần thiết; API local cô lập, không có consumer hoặc yêu cầu tài liệu, không cần gọi documenter theo nghi thức. Worker không khởi động lại orchestration hoặc đăng ký contract/review artifacts. Sửa report giữ lại scope/reviews/evidence còn hợp lệ, không tự lặp cả vòng kiểm tra chỉ vì sai trường JSON.

Các điểm trên là lỗi hoặc rủi ro xác nhận từ source/probe. Chưa có trace đủ chi tiết để kết luận chúng giải thích bao nhiêu trong mức tăng 47,1% token và 36,413 phút của mẫu trước. Hook-launch diagnostic cũ median 75,203 ms cũng không chứng minh chi phí workflow model.

## Bản cài cuối và kiểm chứng

Bài bốn lượt cuối hoàn thành trên bản đã cài sau đây:

| Thành phần | SHA-256 |
|---|---|
| Policy/agent/skill behavior | `8603d7b719515b2534727b5e01cbbe742a1029a955c9c8a741d7cf3f07a9fc59` |
| `verification_gate.py` | `01d03c2254579d5411e7175f8b2e641f22d385f8a20dba75a884ea14bcb3869e` |
| `lifecycle_guard.py` | `a991241467db9e064533ce4b82a75edf88d1799c3023c36c62abb8d6d5cc3ba9` |
| Eval runner | `ae5aa45dbeeaf7be8c6f6a57429b80fd392edff785fc28596198a8f2524a9422` |

Full source check cuối: **300 test Python (3 skip) và 15 test Node** đạt. Installer exit 0; runtime source, runtime đã cài và policy trong global managed block khớp chính xác trước live eval. Phần global ngoài managed block là nội dung riêng của người dùng, không yêu cầu toàn file bằng source. Behavior digest không bao gồm runtime Python, nên ghi riêng các hash runtime. Không thay quyền toàn cục.

Các probe browser, protocol ngắn và profile một lượt trước đó dùng bản `d56df5...`, không phải bằng chứng live cho fingerprint cuối:

| Thành phần bản trước | SHA-256 |
|---|---|
| Policy/agent/skill behavior | `d56df5ca2d319dddedf811b68f44efcc11e60df7838804ec03bce0f194005d82` |
| `verification_gate.py` | `40f6e771811347bb3020fa0fa1979654c1ce693770e38403fab17b0c1ca30932` |
| `lifecycle_guard.py` | `572a34717e74349cd5f97d5e9d8578b10e8922cc5cd829b3d9b77da8ee0f0708` |
| Eval runner release | `cc9477825e3c2144aa087ee73bfc5f4a3085b16f142ab0415547d5cb29f44cc6` |

Full source check của bản trước: **286 test Python (3 skip) và 15 test Node** đạt trong 84,293 giây; installer exit 0, source/runtime đã cài khớp. Các lần parser chưa release có runner hash riêng trong artifact; không gộp chúng thành eval cuối.

Regression checks bao gồm response sửa thay thế response trước, giữ từ chối nhiều envelope trong response cuối, bounded/privacy repair hints, bằng chứng cũ/lỗi không được đề xuất, thiếu hoặc partial completion claim không được chấm hoàn thành, và native-dispatch discovery không coi cache là quyền thực thi.

## MCP thật trên bản cuối `8603d7...` đã cài

Probe `adaptive-browser.json` dùng model `gemini-3.8-flash-high`, CLI 1.3.3, không có gợi ý tool/inventory cho model. Operator mở `/agents` để xác nhận Default và `/mcp` để thấy Playwright ready trước prompt. Model gọi MCP native, operator cấp quyền riêng cho navigate → snapshot → click → snapshot: **bốn lần Ask**, không always-allow hoặc thay quyền toàn cục.

Final report có initial text và exact confirmation khớp dữ liệu server; có browser page hit và confirmation hit, xác nhận rendered interaction. Không quan sát dispatcher `unknown tool` hoặc selector-engine error. Behavioral probe đạt; không dùng thời gian 338,336 giây để so sánh workflow vì gồm operator inspection và chờ cấp quyền.

Model bỏ `Harness:` status line, không quan sát được route. Vì vậy probe này chứng minh hành vi browser và native execution trong session đã kiểm tra readiness, **không chứng minh tuân thủ routing hoặc tự khởi tạo cold-start không có operator**. Không quy kết riêng policy cho phục hồi.

## MCP thật trên bản `d56df5...` đã cài

Model `gemini-3.8-flash-high`, CLI 1.3.3. Operator kiểm tra `/agents` ở Default và `/mcp` báo Playwright ready **trước** prompt. Không gửi gợi ý tool/inventory cho model. Có sáu lần cấp quyền riêng: navigate, snapshot, click, click, snapshot và close. Không có always-allow hoặc thay quyền toàn cục.

Native dispatch và tương tác rendered page được xác nhận. Model báo đúng initial text và exact confirmation trong final report; server ghi nhận page hit và confirmation hit. Click đầu gặp `Unknown engine ref while parsing selector`; lần click sau phục hồi và thực hiện đúng thao tác. Không quan sát dispatcher `unknown tool`.

Đây là **thành công thực thi trong session đã kiểm tra readiness**, chưa chứng minh cold-start tự khởi tạo hoàn toàn không có operator inspection. Source policy và điều kiện startup cùng thay đổi nên không quy phục hồi riêng cho policy. Route model báo là `DIRECT`: probe không chứng minh tuân thủ worker routing yêu cầu của harness. Thời gian quan sát 462,65 giây gồm startup inspection và chờ cấp quyền, loại khỏi so sánh độ trễ workflow.

## Lựa chọn MCP mô phỏng trên bản cuối

Bài selection đạt **5/5**, route `REVIEW_ONLY`, total token **21.724**; subprocess 31,835 giây và toàn runner 32,249 giây. Trace không có tool calls: đây là kiểm tra chọn capability theo tình huống, **không phải bằng chứng thực thi MCP**. Thực thi thật được chứng minh riêng trong browser probe phía trên.

Thời gian subprocess mới thấp hơn lần tối ưu trước 41,991 giây, nhưng vẫn cao hơn baseline 23,262 giây. Vì vậy không kết luận mọi loại tác vụ đều nhanh hơn baseline.

## Chẩn đoán protocol trên bản `d56df5...` đã cài

- Synthetic Stop probe: 22,664 giây, hai response steps, final sentinel hiện diện và draft sentinel không còn trong response dùng để chấm. Đây là bằng chứng tách final response trong probe này, không chấm lại lần bốn lượt lịch sử.
- Native error-step probe: 23,239 giây, một `view_file` thật bị lỗi, một step `ERROR`, final response `DONE` phục hồi được. Không giả lập tool result để gọi đây là live evidence.
- Native subagent release probe: 59,675 giây, quan sát một subagent step thực và final sentinel; không chỉ dựa vào model tự khai rằng đã gọi worker. Probe literal này không đo chi phí worker trong bài waiting list.

Các lần bốn lượt trước release vẫn giữ là không hoàn thành: lần đầu lỗi metadata sau khoảng 359,7 giây, chưa có turn summary và chưa xác định được nguyên nhân chính xác; v2 bị operator dừng khi biết parser chưa hỗ trợ public `ERROR` (heartbeat cuối 178,773 giây); v3 lỗi `conflicting or repeated completed step` sau 212,921 giây, chưa có score. Probe ngắn riêng sau đó xác nhận native tool → subagent promotion, nhưng không có đủ retained frame evidence để quy chính xác mọi lỗi cũ cho cùng cơ chế.

Một lần adaptive bốn lượt dùng bản harness cuối nhưng runner trước observer fix bị operator dừng trước khi lượt một hoàn thành (heartbeat 209,872 giây). Không có turn summary hoặc điểm behavioral/completion; không dùng làm latency benchmark. Lần bốn lượt `final-multiturn` sau đó hoàn thành với runner cuối trong bảng fingerprint; kết quả ghi ở phần so sánh.

## Profile lượt đầu và sửa workflow tiếp

Lượt đầu release `d56df5...` hoàn thành với terminal `SUCCESS`, route `IMPLEMENT`, một claim trong terminal aggregate và một claim trong final response. Operator dừng khi lượt hai đang chạy (heartbeat cuối khoảng 1.049,575 giây), trước khi có kết quả bốn lượt. Không có điểm 8/8 hoặc `success: true` cho bài này.

So với lượt đầu bản tối ưu trước: wall tăng từ 815,310 lên **921,322 giây** (khoảng +13,0%), total token giảm từ 651.323 xuống **546.782** (khoảng −16,1%). Đây là đối chứng lượt đầu, không phải so sánh tổng bốn lượt hoặc tốc độ ổn định.

Trace main quan sát 72 response steps, hai subagent steps, 51 `run_command` calls với tổng 21,866 giây và 80.038 output bytes; 11 command calls trùng fingerprint. Có một `invoke_subagent` và một `send_message`. Số command trùng không tự chứng minh checks dư: có thể là red/green, sửa lỗi, hoặc kiểm chứng lại sau write. Các counter không giữ command text hay worker roles. Vì chỉ có hai subagent steps, trace không chứng minh một implementation hop riêng đã diễn ra.

Observed main local-command runtime chỉ chiếm khoảng 2,4% wall lượt đầu. Phần còn lại có thể gồm model/provider, worker, orchestration và chờ; không đủ dữ liệu để chia chi phí hoặc kết luận orchestration là nguyên nhân duy nhất.

Bản cuối đã áp dụng cho normal low-risk `IMPLEMENT`: independent verifier phải pass scope trước edits; main trực tiếp triển khai, chỉ delegate implementer khi người dùng yêu cầu hoặc parallel ownership/context isolation có lợi thực tế; sau final check bundle, chính verifier read-only nhận full AC/revision/diff/checks để đánh giá delivery mới. Main không tự đánh giá delivery. Complex workflow, v2 ledger/evidence, inline exclusions và `Ask` giữ nguyên. Việc bỏ mandatory implementation hop giải quyết một nguồn chi phí từ policy. Eval cuối nhanh hơn trong mẫu đã đo, nhưng chưa xác định được mức đóng góp riêng của sửa đổi này.

## Milestone lượt đầu trên bản cuối

`final-multiturn-progress.json` ghi nhận lượt một `SUCCESS`, route `IMPLEMENT`, **315,412 giây**, **162.282 total token**. Terminal aggregate và final response đều có một claim. Phần này giữ đối chứng riêng lượt đầu; kết quả độc lập toàn bài nằm ở phần tiếp theo.

| Lượt đầu | Bản tối ưu trước | Bản sửa trung gian `d56df5...` | Bản cuối `8603d7...` |
|---|---:|---:|---:|
| Wall subprocess | 815,310 giây | 921,322 giây | 315,412 giây |
| Total token | 651.323 | 546.782 | 162.282 |

Trong mẫu lượt đầu, wall giảm **61,31%** và total token giảm **75,08%** so với bản tối ưu trước; so với bản trung gian, giảm tương ứng **65,77%** và **70,32%**. Không dùng các tỉ lệ này để dự đoán tổng bốn lượt, chứng minh tốc độ ổn định hoặc quy toàn bộ cải thiện cho một sửa policy.

Trace cuối quan sát bảy `run_command` calls, tổng 9,379 giây và 7.034 output bytes, không có command-text fingerprint trùng; 28 response steps, một subagent step và initialization 3,669 giây. Có ba `view_file` errors trước terminal `SUCCESS`, tức phiên tiếp tục được sau lỗi; các lỗi đó không tự trở thành bằng chứng kiểm chứng thành công. Lexical command categories là `git: 2`, `tests: 2`, `other: 3`, với các giới hạn phân loại ở cuối báo cáo.

Các counter cho thấy ít main-session command/response events hơn trong mẫu này. Chúng không xác định worker roles, số scope/delivery assessments thực sự đã diễn ra, token nội bộ từng worker, hoặc đóng góp nhân quả riêng của main-author, observed-ID hint hay điều kiện provider. Giữ independent scope/delivery và Ask là yêu cầu source; một counter thấp không tự chứng minh tuân thủ workflow.

## Bốn lượt và so sánh

Bài cuối giữ bốn prompt tự nhiên nguyên gốc trong cùng conversation, không workflow reminder hoặc model-tool hint thủ công. **8/8 nhóm hành vi runner-owned** đạt, public tests đạt; `completion_claim_error`, `response_contract_error` và `scope_error` đều null; `success: true`. Model tự khai **13/13 AC complete**; con số này là inventory của model, không phải số điểm độc lập. Tám nhóm hành vi cố định kiểm tra cả yêu cầu trước và các bổ sung/thay đổi qua nhiều lượt.

| Chỉ số | Baseline | Tối ưu trước | Bản sửa cuối đã cài |
|---|---:|---:|---:|
| Hành vi độc lập | 8/8 | 8/8 | **8/8** |
| Public tests | Đạt | Đạt | **Đạt** |
| Kết quả tổng thể | Đạt | Không đạt: aggregate nhiều claim | **Đạt** |
| Wall-clock | Khoảng 29 phút | 2.184,796 giây | **1.103,432 giây = 18,391 phút** |
| Usage cuối `total_tokens` | 1.504.646 | 2.213.413 | **551.994** |
| Browser MCP thật | Đạt, có gợi ý inventory | Chưa đạt | Đạt, bốn Ask, 0 model tool hints; readiness/thiếu Harness line là giới hạn |
| Lựa chọn MCP mô phỏng | 5/5; 23,262 giây | 5/5; 41,991 giây | 5/5; 31,835 giây subprocess |

So với lần tối ưu trước, wall giảm **49,49%**, total token giảm **75,06%**. So với baseline khoảng 1.740 giây, wall giảm **khoảng 36,58%** và total token giảm **63,31%**. Tỉ lệ thời gian baseline dùng mốc ước lượng, không phải số đo chính xác. Đây là kết quả một mẫu mỗi cấu hình, không phải bảo đảm mức cải thiện cho mọi tác vụ/provider.

| Lượt cuối | Route | Subprocess wall | Aggregate/final claim count | Duplicate command calls trong lượt |
|---|---|---:|---:|---:|
| 1 | `IMPLEMENT` | 315,412 giây | 1 / 1 | 0 |
| 2 | `IMPLEMENT` | 254,799 giây | 1 / 1 | 0 |
| 3 | `IMPLEMENT` | 302,601 giây | 1 / 1 | 0 |
| 4 | `IMPLEMENT` | 229,781 giây | 1 / 1 | 0 |

Mỗi final response chỉ có một `HARNESS_RESULT`, terminal aggregate của từng lượt cũng chỉ có một; không gặp lỗi trùng claim trong bài cuối. Tổng main-session trace có **18 `run_command` calls**, 12,789 giây và 31.466 output bytes; 87 response steps, một subagent step và bảy `send_message` calls. Counter không chứa worker roles nên không tự chứng minh ai đã thực hiện từng scope/delivery assessment hoặc toàn bộ workflow đều tuân thủ; việc chấm độc lập xác nhận hành vi cuối và consistency checks quan sát được.

Usage tích lũy ở result cuối:

| Trường | Bản cuối |
|---|---:|
| `input_tokens` | 481.132 |
| `output_tokens` | 70.862 |
| `thinking_tokens` | 33.027 |
| `cache_read_tokens` | 8.325.192 |
| `total_tokens` | 551.994 |

Usage qua các lượt là tích lũy: chỉ dùng usage cuối, không cộng các lượt hoặc cộng cache vào total. `process-events` cung cấp số response steps, aggregate/final claims, tool categories, thời gian và output bytes đã lọc. Các counter chỉ mô tả events mà runner quan sát; không tự chứng minh thời gian/token bên trong mỗi worker hay nguyên nhân nhân quả.

Runner cuối bổ sung `command_categories_heuristic` với các nhãn cố định `acceptance_metadata`, `tests`, `git`, `source_read`, `other`. Phân loại chỉ tìm chuỗi/regex trong command text ở bộ nhớ; không phân tích shell đầy đủ, quoting, mã Python nhúng, exit status hay ý nghĩa kiểm chứng. Vì vậy nhãn có thể sai và không chứng minh một command là test, evidence hợp lệ hoặc công việc lãng phí. Summary không lưu command text, fingerprint, Cwd, tool input/output content hoặc worker identity; chỉ giữ counter và byte/duration totals. Duplicate counter dùng command-text fingerprint nội bộ, không phân biệt Cwd, nên cũng không tự chứng minh thực thi dư. Output bytes là số byte quan sát, không tương đương context tokens hoặc chi phí model. Không hồi tố các category này cho profile `d56df5...` cũ.

Baseline dùng CLI khác ở một số probe và thời gian khoảng 29 phút là ước lượng. Mỗi cấu hình hiện chỉ có một bài bốn lượt hoàn chỉnh; transport và startup conditions thay đổi. Cần giữ các giới hạn này khi so sánh, không kết luận tốc độ ổn định từ một mẫu.
