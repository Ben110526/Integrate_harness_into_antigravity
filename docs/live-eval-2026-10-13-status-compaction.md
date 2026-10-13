# Eval trạng thái Harness, MCP từ phiên mới và compaction — 13/10/2026

Flash đã đạt **14/14 kiểm tra sau compaction thật**, qua 28 lượt chuẩn bị và một lượt đánh giá cuối, với 824.641 byte lịch sử người dùng. Hai thử nghiệm browser từ phiên mới đều báo đúng dòng `Harness: REVIEW_VERIFY`, nhưng **chưa thực thi được MCP**: model báo thiếu native invoker, không có tool call, browser hit hoặc lần Ask nào. Đối chứng browser sau readiness **đạt**, với bốn lời gọi MCP được duyệt Ask từng lần và dòng Harness hợp lệ; không dùng nó để đổi điểm hai thử nghiệm từ phiên mới.

Artifact tổng hợp: [kết quả đã lọc](../evals/results/2026-10-13-status-compaction.json). Đối chứng trước là [eval ngày 12/10](live-eval-2026-10-12-repaired.md): browser đã thực thi sau khi operator kiểm tra readiness, nhưng thiếu dòng Harness. Điều kiện startup và phiên bản CLI khác nhau, nên hai lần chạy không tạo thành phép so sánh nhân quả riêng cho policy.

## Sửa thiếu dòng Harness

Policy trước chỉ yêu cầu dòng trạng thái trong handoff non-direct. Browser QA có thể bị model xếp `DIRECT`, bỏ dòng này; Stop cũng chưa quan sát việc dùng MCP để nhắc sửa định dạng. Policy mới quy định browser QA là `REVIEW_VERIFY` và main handoff có MCP phải có một dòng plain text:

```text
Harness: <ROUTE>; passed: ...; failed/skipped: ...
```

`PostToolUse` chỉ ghi numeric step cuối của native `call_mcp_tool`, kể cả lần gọi thất bại. State không chứa server name, arguments, result text hoặc check evidence. Observer không trả quyết định cấp quyền, không thay `Ask`, không biến MCP call thành một kiểm tra đạt.

Stop chỉ nhắc khi một MCP step quan sát được nằm sau current user record và trước main response `DONE` tương thích. Nó yêu cầu thay response, báo đúng kết quả và giới hạn thực tế; không chạy lại tool hoặc đổi quyền để sửa dòng. Mỗi user turn chỉ có một lần nhắc; nếu vẫn thiếu, Stop cho kết thúc kèm limitation warning để tránh vòng lặp. Dòng trùng, nằm trong code, route không hợp lệ hoặc field chỉ có khoảng trắng không được coi là dòng hợp lệ.

Leaf assignments, explicit user exact-output formats và abnormal stop được miễn; thiếu, truncated hoặc ambiguous provenance thì fail open. `parentConversationId` dùng để phân biệt leaf. Đây là kiểm tra định dạng có giới hạn, không tự chứng minh nội dung `passed` đúng hoặc mọi yêu cầu đã được hoàn thành.

## Bản cài và kiểm chứng source

Installer exit **0**; bản đã cài được đối chiếu với source trước live eval. Full source check ghi nhận **350 test Python (3 skip), 15 test Node**, plugin inventory, installer idempotence/preservation và pinned-browser doctor đều đạt. Windows không được sửa hoặc coi là đã đạt trong tác vụ này, theo yêu cầu người dùng bỏ qua Windows.

| Thành phần | SHA-256 |
|---|---|
| Policy/agent/skill behavior đã cài | `6ff28253efa1642ba5cfcdae435eea607677413bc9bb23ccf62e7da2927b4e4d` |
| `verification_gate.py` | `e40b32211326b32d36ad36d3569e55a66169b7095bd6ecd1bd8477ef391e537b` |
| `lifecycle_guard.py` | `a991241467db9e064533ce4b82a75edf88d1799c3023c36c62abb8d6d5cc3ba9` |
| `hooks.json` | `a090c2278702e86168fd3c76baf204c1fa4cab73590f080ba6be1a6a22a8c26f` |
| Eval `output_quality.py` | `ae5aa45dbeeaf7be8c6f6a57429b80fd392edff785fc28596198a8f2524a9422` |
| Eval `browser_quality.py` | `fba754a8e7aab01bdc84ddb64b8c40d83209cbf5a7411c3ed087c220897f5180` |

Behavior digest không bao gồm runtime Python; vì vậy giữ hash runtime riêng. Eval compaction được sửa ở runner trong quá trình chẩn đoán; fresh conversation hoàn chỉnh dùng SHA-256 `f0f4d2fa6b7887a442940ddb70cbf1792aeff1996ab7b04b398a398b06af3805`. Các lần partial cũ giữ kết quả lỗi riêng, không rescore bằng runner mới.

CLI đang dùng là **Antigravity 1.3.4**, public binary SHA-256 `9da414c0624c27aa2969a86030a070b5341c0657700512eba70b21725ce253f5`. Public binary hiện tại có `parentConversationId` và `GetParentConversationId`. Bằng chứng schema ban đầu từ public CLI **1.3.3** có hash `96dd362d5583c60485f5277fa64e43dd64c3ff02a2bf109fd683b99777da370d`; đó là binary khác, không gọi chúng là cùng một bản. Không đọc hoặc chuyển OAuth credentials, private endpoints hay private client configuration để chạy eval.

## CI sau push

CI Linux của commit `dfb46ea` đạt. macOS gặp một failure trong test lifecycle có sẵn `test_commit_executable_is_selected_from_its_shell_segment`: hook trả `force_ask` thay vì `ask`; cùng test chạy local đạt. Fixture khởi tạo repo bằng Git trong PATH nhưng inspect bằng `/usr/bin/git`, là staged-inspection test đầu tiên; cold startup hoặc tải CI vượt giới hạn 3 giây là khả năng, chưa chứng minh root cause. Connector GitHub không được cấp quyền rerun job (403).

Follow-up chỉ chuẩn hóa fixture dùng cùng trusted Git cho setup và inspection; vẫn kiểm tra fake untrusted Git không bị chạy, giữ nguyên assertions và runtime Ask/timeout. Bản installed/live eval không đổi behavior hoặc runtime hash. Không đổi điểm live eval theo kết quả CI. Windows không được sửa trong task này.

## Hai thử nghiệm MCP từ phiên mới

Cả hai lần dùng `gemini-3.8-flash-high`, process, conversation, project và workspace mới. Prompt tự nhiên yêu cầu đọc initial text trên rendered page, bấm Confirm registration và báo exact confirmation. Prompt không nêu MCP server, tool name, `/mcp` hoặc dòng Harness. Trước prompt không mở inventory/readiness panel, không gửi model tool hint, không chủ động idle để chờ server ready.

| Điều kiện/kết quả | Prompt ngay lúc launch | Prompt ngay sau UI yield đầu tiên |
|---|---:|---:|
| Operator startup readiness inspections | 0 | 0 |
| Model tool hints | 0 | 0 |
| Native MCP calls quan sát | 0 | 0 |
| One-time Ask approvals | 0 | 0 |
| Browser page/confirmation hits | 0 / 0 | 0 / 0 |
| Initial/exact confirmation text đúng | Không | Không |
| Dòng Harness | Có, `REVIEW_VERIFY` | Có, `REVIEW_VERIFY` |
| Kết quả tổng thể | **Không đạt** | **Không đạt** |

Model ở cả hai lần báo thiếu native MCP invoker và dừng an toàn. Không có bằng chứng dispatch native đã xảy ra; cũng không có bằng chứng dispatcher trả lỗi `unknown tool`. Không đổi quyền toàn cục, không always-allow, không tạo client thay thế. Vì không có tool call, các lần này chưa thực nghiệm được luồng Ask khi MCP thực thi; chúng xác nhận quyền không bị nới để vượt blocker.

Sau task thất bại thứ nhất mới mở `/mcp` để chẩn đoán: Playwright chuyển từ cached ready sang initializing khi panel được mở. Sau task thứ hai mới mở `/agents` để xác nhận Default đang được chọn. Các thao tác sau task không phải startup hint hoặc bằng chứng thành công của prompt ban đầu. Chưa xác định root cause của việc invoker không được công bố trong những phiên mới này.

Thời gian quan sát lần lượt khoảng **500** và **447 giây**, có operator polling; không dùng để kết luận tốc độ browser hoặc mức cải thiện latency. Việc model tự phát dòng Harness trong hai blocked reports chưa chứng minh Stop reminder thực sự được kích hoạt: không có MCP call để observer ghi step.

## Đối chứng MCP sau readiness

Một process/conversation/project/workspace mới được mở, operator kiểm tra `/mcp` cho tới khi Playwright ready rồi gửi cùng kiểu natural prompt, không nhắc server/tool/schema hoặc Harness. Khác với cold trials, đây là startup readiness inspection có chủ ý; không gọi là tự hoạt động ngay từ phiên mới.

Model tự đọc schema và thực thi **4 lời gọi native MCP**: `browser_navigate`, `browser_snapshot`, `browser_click`, `browser_snapshot`. Từng lời gọi được duyệt bằng **Yes, allow tool call** một lần. Một yêu cầu của subagent cần mở Ask bằng `Ctrl+K` trước khi chọn; khoảng chờ thao tác này nằm trong wall observation, không phải model latency. Không chọn always-allow hoặc lưu settings. Native UI quan sát hai subagent; không dùng sự hiện diện đó để khẳng định độc lập kiểm chứng.

Loopback server ghi browser page hit và confirmation hit. Final handoff báo đúng initial text, đúng random confirmation sau thao tác bấm, và một dòng `Harness: REVIEW_VERIFY; passed: ...; failed/skipped: none`. Scorer đạt tất cả kiểm tra browser/Harness. UI soft-wrap được nối lại chỉ cho dòng footer cuối khi chấm; redraw không được tính là nhiều response hoặc dòng trùng. Không giữ raw handoff, random confirmation hoặc conversation identity trong artifact.

Observation khoảng **554 giây**, gồm operator/readiness/approval delay; không dùng so sánh tốc độ. Không quan sát thấy Stop reminder sửa footer: model đã báo đúng ngay ở handoff cuối. Kết quả xác nhận source đã cài có thể thực thi browser MCP với Ask và có Harness khi invoker ready; chưa xác định nguyên nhân hai cold trials thiếu invoker.

## Chat dài và native compaction

Người dùng chọn tiếp tục **Flash với context 1M**, không chuyển model hoặc hạ context chỉ để tạo compaction. CLI native hiển thị context 1M; `/compact` không có command match trong phiên đã kiểm tra. Không dùng prompt “hãy giả vờ đã compact”, không coi model tự khai hoặc một checkpoint event là bằng chứng compaction.

Eval gửi lịch sử thật qua first-party CLI, giữ conversation identity. Mười hai core turns cung cấp các phương án workshop, yêu cầu đầu, sửa số người/budget, hủy một phương án và định dạng cuối. Những lượt archive bổ sung dữ liệu Cafe không đủ điều kiện để tăng context mà không thay yêu cầu đang có. Mỗi batch tối đa 50 KiB, tối đa **80 batch** (khoảng 4 MiB); tổng user history có hard limit **5 MiB**. Driver kiểm tra theo stage, không khai rằng các lượt chưa hoàn thành đã được gửi thành công.

Final prompt không nhắc lại label, timezone, budget, số người hoặc phương án bị hủy. Scorer độc lập tính lựa chọn tối ưu từ toàn bộ constraints hiện hành, kiểm tra đúng output shape, yêu cầu đầu, corrections, approval/no-message constraints, Harness line, conversation identity và không có task tool/delegation activity.

Compaction chỉ đạt khi có native UI evidence riêng: divider `Compacted` cùng context giảm ở boundary quan sát được, hoặc native notification/divider chính xác `Conversation compacted` với nguồn gốc UI đã xác nhận. Tham số `manual` phân biệt compaction thủ công và tự động; không suy ra từ lời model. Model prose không được truyền vào constructor này. Nếu chưa quan sát compaction, có thể chấm retention diagnostic riêng, nhưng `overall_pass` cho compaction vẫn false.

Các lần lỗi trước fresh stream vẫn được giữ riêng:

| Lần thử | Kết quả quan sát | Kết luận được phép |
|---|---|---|
| One-shot đầu | Lỗi terminal status sau **63,493 giây** | Không có điểm sau compaction; frame lỗi cũ không được giữ để xác định nguyên nhân chi tiết |
| Retry core | Hoàn thành 6 lượt rồi terminal `ERROR`, nhãn đã lọc `unavailable`, **175,079 giây** | Core history chưa hoàn thành; không suy ra quota/provider root cause |
| Persistent stream resume | `ERROR`/`unavailable` sau **20,677 giây**, conversation khớp, native turn count 8 | Same-ID continuity quan sát được; không phải bằng chứng retention hoặc compaction đạt |
| Fresh persistent stream core | 12 lượt hoàn thành; chặng archive đầu bị `503 UNAVAILABLE` trước init | Giữ nguyên 12 lượt, không tính lượt lỗi là hoàn thành |
| Operator driver no-op stage | Đóng một stream chưa gửi prompt làm runner báo event sau final, **5,191 giây** | Lỗi orchestration riêng; sửa driver để bắt đầu trực tiếp archive, không đổi scorer |
| Tiếp tục cùng fresh conversation | 16 archive batch hoàn thành, native compaction được quan sát, final **14/14** | Retention sau compaction đạt trong mẫu này |

Fresh conversation hoàn thành **29 lượt**: 12 core, 16 archive và final evaluation. Lịch sử chuẩn bị là **824.641 byte**, trong đó archive 817.687 byte. Scorer đạt **14/14**: yêu cầu label/timezone đầu, attendee/budget đã sửa, tập phương án Library tối ưu còn hiệu lực sau cancellation, hỏi trước booking, không gửi tin nhắn, output shape/Harness, continuity, đủ lượt và không task tool/subagent activity.

Native TUI full render được đọc trong bộ nhớ và có divider `Conversation compacted` với đường phân cách native; hai lần xuất hiện do redraw, không coi là hai lần compact. Đây là bằng chứng tự động, không phải model prose hay chỉ checkpoint event. Context native sau core là khoảng **39,0k/1M**, sau archive16 khoảng **85,2k/1M**. Không đo được token ngay trước/sau boundary và không xác định chính xác index boundary; artifact để trống index đó. Các lượt sau preparation và final nằm sau divider quan sát được. Runner dùng nguồn status UI tương đương `native_ui_status("Conversation compacted", manual=False)`.

Tổng thời gian của **các lượt model thành công là 569,893 giây**; wall của continuation/archive/final là **449,923 giây**, gồm các lần kiểm tra UI và không bao gồm core trước đó. Không cộng các số này để tạo một benchmark, không cộng usage tích lũy hoặc cache vào total. Usage cuối conversation: **582.472 total tokens**, input 565.826, output 16.646, thinking 15.391, cache-read 2.056.446. Đây là workload khác bài code bốn lượt trước, nên không kết luận nhanh hơn/chậm hơn từ hai bài.

Không có bản baseline compaction của harness trước. Một mẫu thành công chứng minh khả năng giữ các yêu cầu trong tình huống này; chưa chứng minh mức cải thiện nhân quả của policy hoặc độ ổn định qua nhiều lần.

## Giới hạn còn lại

- Dòng Harness hiện diện trong hai blocked reports và một browser handoff thành công. Repair reminder chưa được quan sát live vì handoff cuối đã đúng; cơ chế reminder có regression tests.
- Tự khám phá và thực thi MCP ngay từ cold start chưa đạt. Readiness control thành công là điều kiện riêng; nguyên nhân client không công bố invoker ở cold trials chưa xác định.
- Retention sau compaction đạt 14/14 trong một mẫu; exact boundary index và token drop tại boundary chưa đo được. Không dùng số token tích lũy làm context usage.
- Counter event và consistency checks không chứng minh mọi câu `passed` đúng về ngữ nghĩa. Browser HTTP hits cần kết hợp native tool observations để khẳng định thực sự bấm nút; task tools/delegation phải được kiểm tra riêng.
- Một mẫu mỗi điều kiện không đủ kết luận độ ổn định hoặc nguyên nhân thuộc riêng policy, provider hay startup. Quyền Ask giữ nguyên trong source và các lần chạy này.
