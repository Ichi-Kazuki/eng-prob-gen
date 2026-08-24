# TOEFL ITP Written Expression (Part B) — Analysis Report

対象: `source/` に存在する ETS公式 TOEFL ITP Practice Test の Section 2「Structure and Written
Expression」のうち **Part B: Written Expression（Error Identification, Q16–40）のみ**。
Part A: Structure（Q1–15）は対象外（`STRUCTURE_ANALYSIS_REPORT.md` を参照）。

**対象Practice Test（5本、`source_id`）**

| source_id | ファイル |
|---|---|
| Practice Test B | `source/Practice Test B Sec 2 SWE.pdf` |
| Practice Test C | `source/Practice Test C Sec 2 SWE.pdf` |
| Practice Test D | `source/Practice Test D Sec 2 SWE.pdf` |
| Practice Test E | `source/Practice Test E Sec 2 SWE.pdf` |
| Practice Test F | `source/Practice Test F Sec 2 SWE.pdf` |

`source/` に Practice Test A のファイルは存在しないため、"Test A" は分析対象に含まれていない。

**総分析問題数**: 125問（25問 × 5テスト）
**分類基準**: `analysis/GRAMMAR_TAXONOMY.md` / `analysis/grammar_taxonomy.json`（Structure分析と
同一のtaxonomyを再利用。唯一の基準として使用）
**データセット**: `analysis/written_expression_items_all.json` / `analysis/written_expression_items_all.csv`

**数値整合性検証**: 本レポート作成前に `analysis/_verify_we_stats.py` をPythonで実行し、以下を
すべて確認済み（詳細は末尾セクション9）。
- 総問題数 = 125 ✅
- `primary_target` 合計 = 125 ✅
- `correct_answer` position 合計 = 125 ✅
- `tested_error_type` 合計 = 125 ✅
- `error_span.span_type` 合計 = 125 ✅
- `error_location` 合計 = 125 ✅
- `error_scope` 合計 = 125 ✅
- `syntactic_complexity` / `error_detectability` / `distractor_plausibility` /
  `estimated_difficulty_ai` 各分布の合計 = 125 ✅（4指標すべて）
- `underlined_parts` 総数 = 125 × 4 = 500 ✅
- `correct_answer` / `error_span.position` / `underlined_parts.is_error=true` の三者照合 =
  125問中ミスマッチ0件 ✅

---

## 1. Grammar distribution

### 1.1 primary_target 別（15カテゴリ中11カテゴリが出現）

> **taxonomy v1.1更新（2026-08-23）**: Written Expressionで発見されたtaxonomy gapの精査により、
> 新カテゴリ`WORD_CLASS_FORM`（品詞選択・派生形）を追加し、該当する14問を
> `WORD_ORDER_MODIFICATION` / `VERB_COMPLEMENTATION` / `CLAUSE_STRUCTURE` /
> `COMPARATIVES_DEGREE`から再分類した。以下の表はこの更新を反映した最新値。詳細は
> `analysis/GRAMMAR_TAXONOMY_CHANGELOG.md`を参照。

| primary_target | count | % |
|---|---:|---:|
| REFERENCE_AND_DETERMINERS | 28 | 22.4% |
| VERB_COMPLEMENTATION | 16 | 12.8% |
| PARALLEL_STRUCTURE | 15 | 12.0% |
| WORD_CLASS_FORM | 14 | 11.2% |
| NONFINITE_VERB_PHRASES | 13 | 10.4% |
| VERB_FORM_VOICE | 10 | 8.0% |
| CONNECTORS_CONJUNCTIONS | 7 | 5.6% |
| RELATIVE_CLAUSES | 7 | 5.6% |
| CLAUSE_STRUCTURE | 7 | 5.6% |
| WORD_ORDER_MODIFICATION | 5 | 4.0% |
| COMPARATIVES_DEGREE | 3 | 2.4% |

合計 28+16+15+14+13+10+7+7+7+5+3 = 125問で一致を確認。未出現の4カテゴリは
`NOUN_CLAUSES` / `ADVERBIAL_CLAUSES` / `INVERSION` / `EXISTENTIAL_EXPLETIVE`。これはStructure
セクションとの明確な違いである。Written Expressionは「一文の中に埋め込まれた語・句レベルの誤り」
を発見させる形式のため、節全体の存在・接続（NOUN_CLAUSES/ADVERBIAL_CLAUSES/INVERSION/
EXISTENTIAL_EXPLETIVEが典型的にテストする構文選択そのもの）よりも、語のカテゴリ・形・照応関係
（REFERENCE_AND_DETERMINERS, VERB_COMPLEMENTATION, WORD_CLASS_FORM, PARALLEL_STRUCTURE等）が
主戦場になっていることが数字上に表れている。最頻出の`REFERENCE_AND_DETERMINERS`（22.4%）は、
代名詞・限定詞の一致・形選択の誤りがこの形式の"核"であることを示す。新設の`WORD_CLASS_FORM`
（11.2%、14問）が3番目にNONFINITE_VERB_PHRASESに次ぐ規模で出現したことは、
「文中の1語の品詞・派生形選択」がWritten Expressionにおいて`REFERENCE_AND_DETERMINERS`に次ぐ
主要な出題パターンであり、taxonomy v1.0では独立したカテゴリを持たなかったこと自体が
分類上の欠落だったことを裏付けている。

### 1.2 subtype 別

125問に対し **124種類のユニークなsubtype**が出現し、まったく同一のsubtype文字列が使われたのは
以下の1件のみ（他はすべて1問ずつの固有subtype）。

| subtype | count |
|---|---:|
| degree word + result clause: 'so...that' required instead of 'very...that' | 2 |

Structure分析（70/75 unique）と同様の傾向で、`subtype`が問題ごとの具体的構文をほぼ1対1で
記述していることが確認できる。詳細な全subtype一覧は`written_expression_items_all.json` /
`.csv`を参照。

---

## 2. Correct answer position

| 選択肢 | count | % |
|---|---:|---:|
| A | 24 | 19.2% |
| B | 37 | 29.6% |
| C | 31 | 24.8% |
| D | 33 | 26.4% |

Structure分析（21.3%〜28.0%の範囲でほぼ均等）と比べると、Written ExpressionではAがやや少なく
（19.2%）、Bがやや多い（29.6%）。4択全体としては依然として大きな偏りとは言えない範囲内だが、
新規問題生成時にはA以外にもやや均等に誤り位置を配分する設計が望ましい。

---

## 3. Error type（tested_error_type）

全125問の誤り選択肢（各問1つ）を対象。`tested_error_type`は15種の固定語彙から選択
（`analysis/GRAMMAR_TAXONOMY.md`に準拠、Reviewerによる横断チェック済み）。

> **taxonomy v1.1更新（2026-08-23）**: 新設の`wrong_preposition_collocation`（前置詞コロケーション
> 専用）と`wrong_degree_form`（比較級/最上級・程度語の混同専用）を追加し、以前`wrong_complementation`
> に強制的に分類されていた14問をこの2値に再分類した。以下の表はこの更新を反映した最新値。

| tested_error_type | count | % |
|---|---:|---:|
| incorrect_part_of_speech | 35 | 28.0% |
| wrong_verb_form | 21 | 16.8% |
| agreement_error | 21 | 16.8% |
| wrong_preposition_collocation | 12 | 9.6% |
| incorrect_relative_marker | 6 | 4.8% |
| extraneous_element | 6 | 4.8% |
| missing_required_element | 6 | 4.8% |
| wrong_word_order | 5 | 4.0% |
| wrong_voice | 4 | 3.2% |
| incorrect_reference | 3 | 2.4% |
| incorrect_subordinator | 3 | 2.4% |
| wrong_degree_form | 2 | 1.6% |
| double_subject | 1 | 0.8% |

Structureの誤答分布（missing_required_element / extraneous_element / wrong_word_order /
fragmentが上位を占め、64%）とは対照的に、Written Expressionでは`incorrect_part_of_speech`
（28.0%）・`wrong_verb_form`（16.8%）・`agreement_error`（16.8%）の3種で全体の61.6%を占める。
これは形式の違いを反映している。Structureは「文全体を完成させる語句を選ぶ」形式のため
構造全体（節の完全性・語順）の誤りが主だが、Written Expressionは「すでに完成した文の中の
1箇所」を指摘する形式のため、語の形態・品詞・一致という局所的な誤りが主戦場になる。
`fragment`（節の非完全性）は本セクションでは0件——文が常に完成した状態で提示される
Written Expressionの形式上、原理的に出現しない誤りタイプである。`wrong_preposition_collocation`
（9.6%）が新設カテゴリとして4番目に多いことは、前置詞コロケーションの誤りがWritten Expression
に特有の主要な出題パターンでありながらtaxonomy v1.0では専用の語彙を持たなかったことを示す。
`wrong_complementation`は0件——本セクションに残っていた全事例が今回の再分類で解消された。

---

## 4. Error span type

`error_span.span_type`（誤りを含む下線部の表層的な文法カテゴリ）

| span_type | count | % |
|---|---:|---:|
| noun_phrase | 24 | 19.2% |
| verb_phrase | 22 | 17.6% |
| adjective | 16 | 12.8% |
| prepositional_phrase | 15 | 12.0% |
| pronoun | 9 | 7.2% |
| relative_marker | 7 | 5.6% |
| gerund_phrase | 6 | 4.8% |
| adverb | 5 | 4.0% |
| determiner | 5 | 4.0% |
| conjunction | 4 | 3.2% |
| participial_phrase | 4 | 3.2% |
| infinitive_phrase | 3 | 2.4% |
| comparative_marker | 3 | 2.4% |
| quantifier | 2 | 1.6% |

上位4種（noun_phrase / verb_phrase / adjective / prepositional_phrase）で全体の61.6%を占める。

---

## 5. Grammatical role of underlined parts

`underlined_parts`は全125問×4選択肢＝**500エントリ**。うち誤りを含むもの（`is_error: true`）は
問題数と同じ125件、誤りを含まないもの（ダミーの下線部）は375件。

### 5.1 誤りを含む下線部の grammatical_role（n=125）

| grammatical_role | count | % |
|---|---:|---:|
| noun_phrase | 24 | 19.2% |
| verb_phrase | 22 | 17.6% |
| preposition | 12 | 9.6% |
| adjective | 12 | 9.6% |
| main_verb | 10 | 8.0% |
| pronoun | 9 | 7.2% |
| relative_pronoun | 7 | 5.6% |
| adverb | 7 | 5.6% |
| conjunction | 4 | 3.2% |
| subject | 4 | 3.2% |
| predicate_adjective | 4 | 3.2% |
| determiner | 3 | 2.4% |
| quantifier | 2 | 1.6% |
| noun_modifier | 2 | 1.6% |
| article | 2 | 1.6% |
| gerund | 1 | 0.8% |

### 5.2 誤りを含まない下線部（ダミー）の grammatical_role（n=375）

| grammatical_role | count | % |
|---|---:|---:|
| noun_phrase | 93 | 24.8% |
| main_verb | 59 | 15.7% |
| verb_phrase | 47 | 12.5% |
| adjective | 41 | 10.9% |
| preposition | 25 | 6.7% |
| subject | 16 | 4.3% |
| adverb | 16 | 4.3% |
| noun_modifier | 15 | 4.0% |
| conjunction | 13 | 3.5% |
| quantifier | 11 | 2.9% |
| relative_pronoun | 9 | 2.4% |
| predicate_adjective | 7 | 1.9% |
| gerund | 6 | 1.6% |
| auxiliary | 5 | 1.3% |
| infinitive_marker | 4 | 1.1% |
| determiner | 2 | 0.5% |
| object | 2 | 0.5% |
| prepositional_phrase | 2 | 0.5% |
| pronoun | 1 | 0.3% |
| article | 1 | 0.3% |

ダミー下線部では`main_verb`（15.7%）が誤り下線部（8.0%）より約2倍出現しやすい——正しい主動詞を
ダミーとして提示する頻度が高いことを示す。逆に`preposition`は誤り下線部（9.6%）の方がダミー
（6.7%）よりやや出現しやすく、前置詞誤り（collocation/complementation系、後述セクション8参照）
が本セクションの主要な出題パターンの一つであることと整合する。

---

## 6. Error location / Error scope

### 6.1 error_location（文中での誤り位置、5値）

| error_location | count | % |
|---|---:|---:|
| sentence_final | 31 | 24.8% |
| late | 31 | 24.8% |
| middle | 28 | 22.4% |
| early | 22 | 17.6% |
| sentence_initial | 13 | 10.4% |

文の後半（late + sentence_final = 49.6%）に誤りが置かれる傾向がやや強く、文頭（sentence_initial
= 10.4%）は少ない。これは、文の主部・冒頭の導入句は受験者が読み始める際に注意深く処理される
一方、文末に近い修飾語句・補語部分は読み飛ばされやすく、誤りを隠しやすいという出題側の意図を
反映している可能性がある。

### 6.2 error_scope（誤りの影響範囲、4値）

| error_scope | count | % |
|---|---:|---:|
| local | 68 | 54.4% |
| clause_level | 42 | 33.6% |
| sentence_level | 9 | 7.2% |
| cross_clause | 6 | 4.8% |
| **合計** | **125** | **100%** |

過半数（54.4%）が`local`（誤りの検出に周辺の1〜2語だけを見れば足りる)。`cross_clause`
（節をまたいだ照応・一致が必要）はわずか4.8%で、Written Expressionの誤りの多くは局所的な
文法チェックで検出可能な設計になっていることが分かる。なお、Reviewerのレビューでは
「関係代名詞の先行詞選択の誤り」パターンにおいて`sentence_level`と`clause_level`の使い分けが
テスト間でやや割れていることが指摘されている（先行詞特定は原理的に節をまたぐ判断を要するため、
明確な基準線を引きにくい）。これは今回は強制的な統一を行わず、将来のtaxonomy定義の明確化課題
として記録する。

---

## 7. Sentence and clause characteristics

### 7.1 sentence_word_count

| 指標 | 値 |
|---|---:|
| mean | 20.05 |
| median | 20 |
| min | 10 |
| max | 33 |
| stdev | 4.27 |

分布（5語ビン）:

| 語数帯 | count |
|---|---:|
| 10–14 | 11 |
| 15–19 | 47 |
| 20–24 | 50 |
| 25–29 | 15 |
| 30–34 | 2 |

Structure（mean 19.97, max 27）とほぼ同水準の平均語数だが、最大値はやや長い（33語）。
Written Expressionは1文全体を読ませて誤りを探させる形式のため、まれに長めの複文が出題される。

### 7.2 clause_count

| 指標 | 値 |
|---|---:|
| mean | 1.59 |
| median | 2 |

分布:

| clause_count | count |
|---|---:|
| 1 | 59 |
| 2 | 58 |
| 3 | 8 |

Structure（mean 1.80、2節構成が最多49%）と比べ、Written Expressionは単文（1節構成、47.2%）と
2節構成（46.4%）がほぼ拮抗しており、全体としてやや単純な節構造の文が多い。これは、複雑な節
構造そのものを問うのはStructure（Part A）の役割であり、Written Expression（Part B）は
「完成された文の中の局所的な誤り発見」に主眼があるという形式上の違いと整合する。

---

## 8. Difficulty-related features

> **注記**: 以下の指標（`syntactic_complexity`, `error_detectability`, `distractor_plausibility`,
> `estimated_difficulty_ai`）はいずれもETS公式の難易度指標ではない。文の構造・誤りの紛らわしさ等
> からAnalyzer/Reviewerエージェントが構造的に推定した値であり、実際の受験者正答率とは対応しない。

### 8.1 syntactic_complexity（1–5）

| 指標 | 値 |
|---|---:|
| mean | 2.30 |

分布: `1`=15件, `2`=61件, `3`=46件, `4`=3件（`5`は0件）。

### 8.2 error_detectability（1=見つけやすい 〜 5=見つけにくい）

| 指標 | 値 |
|---|---:|
| mean | 2.49 |

分布: `1`=7件, `2`=60件, `3`=48件, `4`=10件（`5`は0件）。中央値付近（2）に集中しており、
極端に見つけにくい（5）誤りは今回のサンプルには存在しない。Reviewerの横断チェックにより、
この指標の方向性（1=easy/5=hard）が全ファイルで一貫して適用されていることを確認済み。

### 8.3 distractor_plausibility（1–5、下線部がもっともらしい"罠"としてどれだけ機能するか）

| 指標 | 値 |
|---|---:|
| mean | 2.48 |

分布: `1`=6件, `2`=57件, `3`=58件, `4`=4件（`5`は0件）。

### 8.4 estimated_difficulty_ai（1–5、AIによる構造的推定値）

| 指標 | 値 |
|---|---:|
| mean | 2.30 |

分布: `1`=18件, `2`=61件, `3`=37件, `4`=9件（`5`は0件）。

---

## 9. Vocabulary domains

125問に対し **112種類のユニークな`vocabulary_domain`**が出現。2回以上出現したのは以下の9件で、
残り103ドメインはすべて1件ずつ（5+3+2×7 + 103×1 = 22+103 = 125で一致を確認）。

| domain | count | % |
|---|---:|---:|
| art history | 5 | 4.0% |
| astronomy | 3 | 2.4% |
| anthropology | 2 | 1.6% |
| geology/earth science | 2 | 1.6% |
| literature/poetry | 2 | 1.6% |
| music | 2 | 1.6% |
| geology/mineralogy | 2 | 1.6% |
| literature/history | 2 | 1.6% |
| economics/history | 2 | 1.6% |
| その他103ドメイン | 各1件 | 各0.8% |

Structure分析（73 unique/75）と同様、ETS公式問題は幅広いアカデミック領域から出題されており、
語彙ドメインの重複はほぼない。`art history`がやや突出しているが、これも5/125（4.0%）に過ぎず、
特定分野への偏りは見られない。

---

## 10. パイプライン品質管理サマリ

- **Analyzer Sub Agent**: 5体（Test B, C, D, E, F、それぞれ1体ずつ）。全125問を分析。
  初回起動時、session使用上限エラーによりTest B/D/E/Fの4体が失敗（Test Cのみ初回で成功）。
  完了済みのTest Cの結果を保持したまま、失敗した4体のみを再起動して回収した
  （既存の完了分はやり直していない）。
- **Reviewer Sub Agent**: 1体。125問・5ファイルを10項目チェックリストに照らして横断レビューし、
  **7件を直接修正**：
  - Test D Q16: `primary_target` を `REFERENCE_AND_DETERMINERS` → `WORD_ORDER_MODIFICATION`
    に変更（Test F Q19の同型パターンとの整合）
  - Test D Q19/Q31/Q37: `primary_target` を `CONNECTORS_CONJUNCTIONS` → `VERB_COMPLEMENTATION`
    に変更（動詞・分詞支配の前置詞コロケーションという確立済みパターンとの整合）
  - Test E Q22: `error_scope` を `sentence_level` → `clause_level` に変更（Test D Q23の同型
    パターンとの整合）
  - Test E Q36, Test F Q31: `taxonomy_issue` を `false` → `true` に変更（他の同型パターンで
    既に立てられていたフラグの立て漏れを修正）
  - なお、レビュー方針として提示されていた「主語動詞の一致は`VERB_FORM_VOICE`に統一すべき」という
    前提はtaxonomy定義とStructureセクションの実データ（`CLAUSE_STRUCTURE`が正）に照らして誤りと
    判明したため、該当6問は変更しなかった（既存の`CLAUSE_STRUCTURE`が正しい）。
  - Reviewer自体も1回目の起動時にsession使用上限エラーで失敗（未確定な編集のみで停止、
    ファイルへの反映なしと確認）。2回目の起動で全10項目のレビューを完走。
- **taxonomy_issue件数（このレポート初版時点）**: **31件**（125問中）。Reviewerが
  `analysis/taxonomy_issues_written_expression.md`に**6件**のtaxonomy拡張候補を記録：
  1. 前置詞・コロケーションの誤りを表す`tested_error_type`が存在しない（14件、全5テストに分布 —
     最大のギャップ。Structure分析時から`wrong_complementation`で代用してきた既存の課題と同種）
  2. 等位接続詞の誤用を表す`tested_error_type`が存在しない（1件、Test E Q20）
  3. 名詞句内の修飾語における品詞混同を表す`primary_target`が存在しない（7件、B/D/F）
  4. 動詞・副詞を修飾すべき箇所の品詞混同を表す`primary_target`が存在しない（3件、B/C/D）
  5. 主語位置での派生語形の誤りを表す`primary_target`が存在しない（1件、Test E Q33）
  6. Structure分析で記録済みの`wrong_degree_form`ギャップ（比較級/最上級混同）はWritten
     Expressionでは再発を確認できず（クロスリファレンスのみ）
  - この時点では`GRAMMAR_TAXONOMY.md` / `grammar_taxonomy.json`は変更していない（記録のみ）。

### 10.1 taxonomy v1.1 更新ラウンド（2026-08-23、追記）

上記6件のgapを精査した結果、以下の taxonomy 拡張を実施した（詳細・判断基準は
`analysis/GRAMMAR_TAXONOMY_CHANGELOG.md`を参照）。

- 新設 `tested_error_type`: `wrong_preposition_collocation`（Issue 1、12問を再分類）
- 新設 `tested_error_type`: `wrong_degree_form`（Issue 6のクロスリファレンスを再検討し、
  Structure Test E Q9-Aの比較級/最上級混同とWritten Expression Test C Q37/Test F Q31の
  "so/very"混同を同一ファミリーとして統合。3問を再分類、うち2問がWritten Expression）
- 新設 `primary_target`: `WORD_CLASS_FORM`（Issue 3・4・5を統合。当初14問と見積もっていたが、
  taxonomy更新後の全200問横断Reviewerが追加で2問（Test D Q25, Test E Q18）を発見し、
  最終的に14問がこのカテゴリに分類された）
- Issue 2（Test E Q20）とTest D Q34・Test E Q18(後にWORD_CLASS_FORMへ再分類)・Test F Q30は
  単一事例のため新カテゴリを見送り、force-fitのまま`taxonomy_issue: true`を維持
  （Test F Q24は既存カテゴリで十分説明可能と判断し`false`へ再評価）

この更新ラウンドで、taxonomy更新の直接適用（27問）＋全200問横断Reviewerによる追加修正
（5問: Test C Q20, Test D Q25, Test E Q18の再分類、Test E Q20の理由文更新）を合わせて
**合計32問**のフィールドが変更された。

**taxonomy_issue件数（更新後・最終）**: **3件**（125問中、D34/E20/F30のみ）。

| | before | after |
|---|---:|---:|
| taxonomy_issue: true | 31 | 3 |
| taxonomy_issue: false | 94 | 122 |

---

## 11. 出力ファイル一覧

- `analysis/written_expression_items_all.json` — 統合データセット（125問、taxonomy v1.1 metadata付き）
- `analysis/written_expression_items_all.csv` — 表形式（Excel/pandas等で扱い可能）
- `analysis/WRITTEN_EXPRESSION_ANALYSIS_REPORT.md` — 本レポート
- `analysis/taxonomy_issues_written_expression.md` — 初回Reviewerが記録したtaxonomy拡張候補（6件、
  うち3件を`GRAMMAR_TAXONOMY_CHANGELOG.md`で採択・実装）
- `analysis/GRAMMAR_TAXONOMY_CHANGELOG.md` — taxonomy v1.0→v1.1の変更履歴と判断基準
- `analysis/raw/written_expression_test_{B,C,D,E,F}.json` — テスト単位の中間ファイル（Reviewer修正済み）
