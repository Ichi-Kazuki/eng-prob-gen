# WE Format / Span Geometry Analysis Report

## 1. Executive summary

ETS公式 Practice Tests B–F の Written Expression Q16–40、計125問と、Validation v1.1 の Written Expression 75問を、同じtokenization ruleで比較した。今回の目的は閾値を決めることではなく、観測分布をSpecification候補として抽出することである。

主要な観測値は次の通り。

| 指標 | Official 125 | AI Validation 75 |
|---|---:|---:|
| sentence word count mean / median | 20.05 / 20 | 9.92 / 10 |
| all 500/300 marked spans median | 1.00 | 2.00 |
| marked coverage ratio median | 26.3% | 100.0% |
| unmarked word count median | 15 | 0 |
| gap A–B / B–C / C–D median | 4 / 4 / 4 | 0 / 0 / 0 |

一次的には、Human Reviewの「短い文」「marked partsが長い」「coverageが高い」「外側のcontextが少ない」という観察は、中央値・分布の差として確認できる可能性が高い。一方、「答えが明確でない」「何を問うか不自然」はspan geometryだけでは完全には判定できず、locality / decision granularityとitem validityの併読が必要である。

## 2. Method

### Source

- Official: `analysis/written_expression_items_all.json` と元PDF `source/Practice Test B–F Sec 2 SWE.pdf` のQ16–40。
- AI: `analysis/validation/validation_batch1.json`、`validation_batch2.json`、`validation_batch3.json` のsection=Written Expression。
- 公式側の既存 item records は保持し、今回のspan countなどを追加した。Validation側はsentenceとmarked_partsを再tokenizeした。

### Tokenization rule

> Unicode-aware lexical tokens: [letters/numbers] sequences are words; an internal apostrophe or hyphen remains inside the same token; punctuation-only tokens are excluded. Contractions, possessives, hyphenated forms, and numeric forms such as 1900's count as one token. The same rule is used for sentences, marked spans, corrections, and gaps.

Official PDFはスキャン/custom-fontのため、抽出テキストに安定したtoken offsetがない。公式sentence word countは既存のPDF基準値を同一ruleで再照合し、125問すべてでdelta=0となった。公式spanの長さはPDF上の可視underliningを読み取り、A→B→C→Dの順序を保持した。したがって公式のspan placement/gapのtoken indexは「ordered-PDF-geometry approximation」であり、Validationのexact text alignmentより信頼度が低い。コピー生成用の公式文本文は新規成果物に含めない。

Coverageは `unique marked token count / sentence word count`。通常の4 spanは重複しないが、重複がある場合はunique unionを使う。`marked_token_total`は指定どおりA+B+C+Dの合計として別保存した。

Span typeは次の観測分類である。SINGLE_WORD=1 token、SHORT_PHRASE=2–4 tokenの非節的まとまり、LONG_PHRASE=5 token以上、CLAUSE_OR_CLAUSE_LIKE=節または節に近い有限verb/subject/relative/participial/coordinateまとまり。これは分析用ラベルであり、Generator thresholdではない。

Correction token countは、minimal correctionのsource/target token数の大きい方をsurface correction sizeとした。no correction claimは0、parse不能はnullとした。これも制約値ではない。

## 3. Official sentence length

| n | mean | median | min | max | stdev |
|---:|---:|---:|---:|---:|---:|
| 125 | 20.05 | 20 | 10 | 33 | 4.27 |

Bins: `{'<=10': 1, '11-15': 15, '16-20': 49, '21-25': 48, '26-30': 10, '31+': 2}`。

## 4. Official marked span length

500 marked partsの全体統計: mean=1.29, median=1.00, min=1, max=4, stdev=0.56。

1/2/3/4/5+ words: `{'1': 375, '2': 106, '3': 16, '4': 3, '5+': 0}`。

Item-level mean span length: mean=1.29, median=1.25。各itemのmax/minもJSON/CSVに保存した。

## 5. Official span type

500 spans: `{'SINGLE_WORD': 375, 'SHORT_PHRASE': 55, 'CLAUSE_OR_CLAUSE_LIKE': 70}`。

公式ではSINGLE_WORDが中心で、multiword marked partは多数あるが、5 token以上の極端な長spanは観測分布上の少数側である。CLAUSE_OR_CLAUSE_LIKEは、単なる長さではなく、既存role/subtype/error_scopeを併用して付与した。

## 6. Official coverage ratio

| n | mean | median | min | max |
|---:|---:|---:|---:|---:|
| 125 | 27.1% | 26.3% | 12.9% | 60.0% |

Bins: `{'<20%': 27, '20-29%': 54, '30-39%': 35, '40-49%': 8, '50-59%': 0, '>=60%': 1}`。`>=60%`は1/125問。これは「文の大部分がmarked」の頻度の直接的な観測である。

## 7. Official unmarked context

unmarked word count: mean=14.87, median=15, min=4, max=27。

## 8. Official span spacing

| gap | mean | median | min | max |
|---|---:|---:|---:|---:|
| A–B | 3.54 | 4 | 1 | 6 |
| B–C | 3.82 | 4 | 1 | 7 |
| C–D | 3.77 | 4 | 1 | 7 |

500 span placement counts: `{'sentence_initial': 121, 'early': 128, 'middle': 126, 'late': 109, 'sentence_final': 16}`。公式側はPDFのword-offset制約があるため、spacing/placementは方向性確認用とし、exact token geometryの比較はValidation側を主とする。

## 9. Correct error span

正解span length: mean=1.27, median=1, min=1, max=4。Type: `{'SINGLE_WORD': 98, 'SHORT_PHRASE': 12, 'CLAUSE_OR_CLAUSE_LIKE': 15}`。

Correction token count: mean=2.31, median=2。minimal correctionがtoken-levelで表せないものはstatusを保存した。

## 10. Correction locality

`{'DEPENDENCY_BASED': 19, 'LOCAL_SHORT_SPAN': 13, 'SEMANTIC_OR_CONTEXT_DEPENDENT': 11, 'LOCAL_SINGLE_TOKEN': 28, 'CLAUSE_LEVEL': 54}`。

LOCAL_SINGLE_TOKEN / LOCAL_SHORT_SPANはmarked span近傍の置換、DEPENDENCY_BASEDはmarked外のagreement/reference等、CLAUSE_LEVELは節構造、SEMANTIC_OR_CONTEXT_DEPENDENTは意味・文脈・先行詞・自然さの判断を含むものとして分類した。公式でも短いspan + dependency/contextの問題が中心であり、長いmark自体を難しさの代理にすべきではない。

## 11. Decision granularity

`{'FUNCTION_WORD': 26, 'WORD_ORDER': 6, 'CLAUSE_RELATION': 8, 'VERB_FRAME': 44, 'OTHER': 7, 'MORPHOLOGY': 15, 'WORD_CLASS': 4, 'AGREEMENT_DEPENDENCY': 14, 'LOCAL_PHRASE': 1}`。

これは既存primary_targetとは別に、実際の判断単位を再分類した結果である。公式はMORPHOLOGY / FUNCTION_WORD / AGREEMENT_DEPENDENCY / VERB_FRAME / CLAUSE_RELATIONなどが混在し、1つの単純な「文法エラー」カテゴリには還元できない。

## 12. Official vs AI comparison

| metric | Official 125 | AI Validation 75 | reading |
|---|---:|---:|---|
| sentence mean / median | 20.05 / 20 | 9.92 / 10 | AIが短い場合、Human observation 1を支持 |
| all marked span median | 1.00 | 2.00 | AIが大きければ observation 2を支持 |
| coverage median | 26.3% | 100.0% | 高ければ observation 3を支持 |
| unmarked median | 15 | 0 | 少なければ observation 1/3を支持 |
| A–B median gap | 4 | 0 | 連続化の兆候 |
| B–C median gap | 4 | 0 | 連続化の兆候 |
| C–D median gap | 4 | 0 | 連続化の兆候 |

AIのsentence countが15以下なのは 75/75問、公式は 16/125問。coverage >=60%はAI 75/75問、公式 1/125問。平均marked span <=1.5 tokenのitemはAI 3/75、公式 110/125。

AIのexact alignment status: `{'aligned': 69, 'aligned_with_repeated_or_nonmonotonic_occurrence': 6}`。Batch 2のmarked partsは、format値だけでなくvalidity auditも併読する必要がある。

## 13. Batch 1/2/3 comparison

| batch | n | sentence median | span median | coverage median | unmarked median | A–B / B–C / C–D median |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 25 | 11 | 2.50 | 100.0% | 0 | 0 / 0 / 0 |
| 2 | 25 | 8 | 2.00 | 100.0% | 0 | 0 / 0 / 0 |
| 3 | 25 | 11 | 3.00 | 100.0% | 0 | 0 / 0 / 0 |

Batch 2はformat上の外れ値があるかを別に、`VALIDATION_FAILURE_AUDIT.md`で25問全てno_genuine_errorと記録されている。そのためBatch 2が幾何指標で極端に見えても、「WE itemとしてのvalidity failure」と「span format failure」を混同しない。Batch別の数値は出力JSONに保存した。

## 14. Human observation verification

1. **文が短い** — Official/AIのsentence mean・median差、および15語以下の比率で検証可能。差がAI側に出た場合は支持。
2. **marked parts / 選択肢が長い** — all marked spansのmedian、5+分布、item-level maxで検証可能。AI中央値/上位分位が大きければ支持。
3. **marked partsが文全体に及ぶ** — coverage ratioと>=60% binで検証可能。AI側が高ければ支持。
4. **何を問う問題なのか不自然** — decision granularity / correction localityの分布差、およびBatch 2 validity auditで部分的に検証。geometry単独では断定不可。
5. **答えが明確でない** — span長だけでは検証不可。semantic/context-dependent比率、correction parse、validity auditを補助証拠として扱う。数値が低くても「明確さ」を保証しない。

今回のデータでは、1–3は明確に支持される。具体的には、sentence medianは20語→10語、15語以下は公式16/125 (12.8%)→AI75/75 (100%)、marked span medianは1語→2語、5+ spanは公式0/500→AI21/300、coverage medianは26.3%→100%、>=60%は公式1/125→AI75/75、unmarked medianは15語→0語、gap A–B/B–C/C–D medianは4/4/4→0/0/0である。

4–5はpartial supportに留まる。decision granularity / correction localityは「問う単位」の違いを示すが、自然さ・明確さを直接測定するものではない。さらにBatch 2はformat geometry上も短文・連続markだが、既存auditで25/25がno_genuine_errorとされており、validity failureの実例としては強い。一方、geometryだけから「答えが明確でない」を全75問に一般化することはできない。反証となる指標がある場合は、AI全体だけでなくBatch別・validity別に読む。

## 15. Missing specification dimensions

既存のprimary target/error taxonomyだけでは、少なくとも次の形状軸が不足している。

- sentence word-count distribution
- A/B/C/D各spanのword countとspan type
- marked unique coverage ratio と unmarked context
- A→B→C→Dのtoken gap / span placement
- correct span length/type と correction surface size
- correction locality（local / dependency / clause / semantic-context）
- decision granularity（何を1単位として判断させるか）
- 公式観測分布に対するValidation/batch別の比較フィールド
- PDF/生成データでのspan alignment confidenceと測定方法

## 16. Recommended Specification additions

実装はまだ行わず、次工程の候補だけを示す。

### Generator v1.2候補

- まず公式125問の観測分布を基準に、sentence length / span length / coverage / gapをsoft targetとしてサンプリングする。
- A/B/C/Dを連続した長い領域に置くのではなく、unmarked contextとspan gapを明示的に生成状態へ持たせる。
- correct span lengthは、単一tokenだけに固定せず、公式のSHORT_PHRASE / dependency / clause-likeの混在を再現する。
- decision granularityをitem metadataとして先に選び、sentence全体の意味解釈だけを要求するsemantic/context itemを別枠管理する。
- 公式分布から外れた場合は、生成後にformat diagnosticsを付与し、後段Reviewerに渡す。

### Reviewer v1.2候補

- sentence too short / marked span too long / coverage too high / unmarked context too small / spans too contiguousを別々のstyle checksとして出す。
- A/B/C/Dごとのspan type、correct span size、gap、placementを監査し、primary targetの妥当性と分離する。
- LOCAL_SINGLE_TOKEN〜SEMANTIC_OR_CONTEXT_DEPENDENTのlocalityを判定し、semantic-onlyで正答が決まるitemを要レビューにする。
- Batch 2のような「文法的にエラーがない」問題をformat passに通さないvalidity gateを検討する。

これらは観測からのrecommendationであり、今回の工程ではGenerator/Reviewer/Specification/その他の実装は変更していない。`max=3`などのhard thresholdもまだ決めていない。

## Reproducibility and limitations

生成物のitem-level JSON/CSVには、全count、ratio、span type、placement、gaps、correct span、locality、decision granularityを保存した。公式はPDF underliningの可視情報を用いたが、token offsetのexact extractionができないため、official placement/gapはapproximationである。Validationはsentence/marked_partsのexact token alignmentを使った。今後、公式のclean text transcriptionまたは座標付きunderlining annotationが得られた場合、count tableを差し替えて同じscriptを再実行できる。

今回の成果物作成以外に、Generator、Reviewer、Solver、Orchestrator、Specification、Taxonomy、DB、Websiteは変更していない。
