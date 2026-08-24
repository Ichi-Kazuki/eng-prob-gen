# TOEFL ITP Structure (Part A) — Analysis Report

対象: `source/` に存在する ETS公式 TOEFL ITP Practice Test の Section 2「Structure and Written
Expression」のうち **Part A: Structure（Incomplete Sentences, Q1–15）のみ**。
Part B: Written Expression（通常Q16–40）は対象外。

**対象Practice Test（5本、`source_id`）**

| source_id | ファイル |
|---|---|
| Practice Test B | `source/Practice Test B Sec 2 SWE.pdf` |
| Practice Test C | `source/Practice Test C Sec 2 SWE.pdf` |
| Practice Test D | `source/Practice Test D Sec 2 SWE.pdf` |
| Practice Test E | `source/Practice Test E Sec 2 SWE.pdf` |
| Practice Test F | `source/Practice Test F Sec 2 SWE.pdf` |

`source/` に Practice Test A のファイルは存在しないため、"Test A" は分析対象に含まれていない
（欠番ではなく、そもそも手元の教材に含まれていない）。

**総分析問題数**: 75問（15問 × 5テスト）
**分類基準**: `analysis/GRAMMAR_TAXONOMY.md` / `analysis/grammar_taxonomy.json`（唯一の基準として使用）
**データセット**: `analysis/structure_items_all.json` / `analysis/structure_items_all.csv`

---

## 1. Grammar distribution

### 1.1 primary_target 別（taxonomy v1.1の15カテゴリ中14カテゴリが出現）

> **taxonomy v1.1更新（2026-08-23）**: Written Expression分析で発見されたtaxonomy gapを受け、
> 新カテゴリ`WORD_CLASS_FORM`を追加した（詳細は`analysis/GRAMMAR_TAXONOMY_CHANGELOG.md`）。
> Structure（Part A）にはこのカテゴリに該当する項目がなく、以下の分布・件数はv1.0時点から
> 変化していない（Structureのprimary_target自体は今回のtaxonomy更新で1件も変更されていない。
> 唯一の変更はTest E Q9の distractor A の`error_type`のみ。セクション7参照）。

| primary_target | count | % |
|---|---:|---:|
| CLAUSE_STRUCTURE | 12 | 16.0% |
| RELATIVE_CLAUSES | 9 | 12.0% |
| NONFINITE_VERB_PHRASES | 9 | 12.0% |
| WORD_ORDER_MODIFICATION | 8 | 10.7% |
| VERB_COMPLEMENTATION | 7 | 9.3% |
| NOUN_CLAUSES | 6 | 8.0% |
| COMPARATIVES_DEGREE | 5 | 6.7% |
| CONNECTORS_CONJUNCTIONS | 5 | 6.7% |
| INVERSION | 4 | 5.3% |
| ADVERBIAL_CLAUSES | 3 | 4.0% |
| EXISTENTIAL_EXPLETIVE | 3 | 4.0% |
| REFERENCE_AND_DETERMINERS | 2 | 2.7% |
| VERB_FORM_VOICE | 1 | 1.3% |
| PARALLEL_STRUCTURE | 1 | 1.3% |

合計 12+9+9+8+7+6+5+5+4+3+3+2+1+1 = 75問で一致を確認。上表の14カテゴリは0件のカテゴリなし
（`VERB_FORM_VOICE` と `PARALLEL_STRUCTURE` はそれぞれ1問のみと出現数が少ない）。未出現なのは
`WORD_CLASS_FORM`（taxonomy v1.1で新設、Written Expression専用の出現パターンで、Structure Part A
の形式にはこの現象を単独で問う設問がない）のみ。上位3カテゴリ（節構造・関係詞節・非定形動詞句）
で全体の40%を占め、TOEFL ITP Structureが「節を正しく構成できるか」を中心に据えていることが
数字上でも裏付けられた。

### 1.2 subtype 別

75問に対し **70種類のユニークなsubtype**が出現し、まったく同一のsubtype文字列が使われたのは
以下の4件のみ（他はすべて1問ずつの固有subtype）。

| subtype | count |
|---|---:|
| main clause (subject + finite verb) identification | 3 |
| predicate nominative after linking verb (be + NP) | 2 |
| appositive noun phrase placement and internal word order | 2 |
| expletive 'there + be' construction vs. pronoun/determiner | 2 |

これは想定どおりの結果である。`primary_target`は再利用可能な大分類として機能した一方、
`subtype`は問題ごとに具体的な構文を記述するためほぼ1対1になる。今後さらに多くの公式問題を
分析すれば、`subtype`の再利用率は上がっていくと見込まれる。詳細な全subtype一覧は
`structure_items_all.json` / `.csv` を参照。

---

## 2. Sentence characteristics

`sentence_word_count`（正解を選んだ場合の完全な文の語数）

| 指標 | 値 |
|---|---:|
| mean | 19.97 |
| median | 20 |
| min | 10 |
| max | 27 |
| stdev | 4.34 |

分布（5語ビン）:

| 語数帯 | count |
|---|---:|
| 10–14 | 11 |
| 15–19 | 22 |
| 20–24 | 27 |
| 25–27 | 15 |

ほとんどの問題は10〜27語の範囲に収まり、20〜24語がボリュームゾーン。極端に短い文
（10語、Test B Q5）や長い文（27語、Test E Q8/Q13, Test F Q1/Q11）も一定数存在する。

---

## 3. Clause characteristics

`clause_count`（定形節のみ。不定詞・動名詞・分詞句は含めない）

| 指標 | 値 |
|---|---:|
| mean | 1.80 |
| median | 2 |

分布:

| clause_count | count |
|---|---:|
| 1 | 27 |
| 2 | 37 |
| 3 | 10 |
| 4 | 1 |

1節構成（単文、非定形修飾句のみ付加）が36%、2節構成（主節+従属節1つ）が最多の49%を占める。
3節以上は15%弱で、複数の従属節が入れ子になる高難度構文（e.g. Test E Q13: free relative +
relative + coordination）は少数派にとどまる。

---

## 4. Difficulty-related features

### 4.1 syntactic_complexity（1–5）

| 指標 | 値 |
|---|---:|
| mean | 2.77 |

分布: `2`=30件, `3`=32件, `4`=13件（`1`, `5`は0件）。中央値付近（2〜3）に集中しており、
公式問題は極端に単純／複雑な構文を避け、中程度の統語的複雑さで出題する傾向が見える。

### 4.2 distractor_similarity（1–5）

| 指標 | 値 |
|---|---:|
| mean | 3.27 |

分布: `2`=2件, `3`=52件, `4`=20件, `5`=1件（`1`は0件）。大半（69%）が`3`（誤答が正解とある程度
似ている）に集中し、選択肢が完全にランダムな語順スクランブル（`5`、Test C Q6）は例外的。

### 4.3 estimated_difficulty_ai（1–5、AIによる構造的推定値）

> **注記**: この値はETS公式の難易度指標ではない。文の長さ・節の入れ子・誤答の紛らわしさ等から
> Analyzerエージェントが構造的に推定した値であり、実際の受験者正答率とは対応しない。

| 指標 | 値 |
|---|---:|
| mean | 2.96 |

分布: `2`=18件, `3`=42件, `4`=15件（`1`, `5`は0件）。倒置構文（INVERSION）・多重埋め込み節を
含む問題（clause_count=3以上）で`4`が集中する傾向。

---

## 5. Vocabulary domains

75問に対し **73種類のユニークな`vocabulary_domain`**が出現。2回出現したのは以下の2件のみで、
残り71ドメインはすべて1件ずつ（2×2 + 71×1 = 75で一致を確認）。

| domain | count | % |
|---|---:|---:|
| botany | 2 | 2.7% |
| zoology/marine biology | 2 | 2.7% |
| その他71ドメイン | 各1件 | 各1.3% |

ETSの公式問題は自然科学・歴史・美術・生物学など幅広いアカデミック領域から出題されており、
語彙ドメインの重複はほぼない。新規問題生成時のドメイン選定では、この幅広さ自体を
仕様の一部として扱う必要がある（詳細は`structure_items_all.csv`の`vocabulary_domain`列を参照）。

---

## 6. Correct answer position

| 選択肢 | count | % |
|---|---:|---:|
| A | 18 | 24.0% |
| B | 21 | 28.0% |
| C | 20 | 26.7% |
| D | 16 | 21.3% |

4択の分布はほぼ均等（21.3%〜28.0%の範囲）で、正解位置に明確な偏りは見られない。

---

## 7. Distractor patterns

全225個の誤答選択肢（75問 × 3distractors）を対象。`error_type`は15種の固定語彙から選択
（`analysis/GRAMMAR_TAXONOMY.md`に準拠、Reviewerによる横断チェック済み）。

> **taxonomy v1.1更新（2026-08-23）**: Written Expression分析で発見されたtaxonomy gapの精査に伴い、
> Test E Q9の distractor A の`error_type`を`incorrect_part_of_speech`から新設の`wrong_degree_form`
> （比較級/最上級の混同を表す専用値）に変更した。詳細は`analysis/GRAMMAR_TAXONOMY_CHANGELOG.md`
> を参照。以下の表はこの変更を反映した最新値。

| error_type | count | % |
|---|---:|---:|
| missing_required_element | 42 | 18.7% |
| extraneous_element | 34 | 15.1% |
| wrong_word_order | 34 | 15.1% |
| fragment | 34 | 15.1% |
| wrong_complementation | 17 | 7.6% |
| incorrect_subordinator | 16 | 7.1% |
| incorrect_part_of_speech | 10 | 4.4% |
| incorrect_relative_marker | 9 | 4.0% |
| wrong_verb_form | 9 | 4.0% |
| double_subject | 9 | 4.0% |
| wrong_voice | 6 | 2.7% |
| incorrect_reference | 2 | 0.9% |
| agreement_error | 2 | 0.9% |
| wrong_degree_form | 1 | 0.4% |

上位4種（missing_required_element / extraneous_element / wrong_word_order / fragment）で
全誤答の64%を占める。これは「必要な要素が欠けている」「余計な要素が入っている」
「語順が崩れている」「節として成立していない」という4パターンが、TOEFL ITP Structureの
誤答設計における最も基本的な"型"であることを示している。逆に`agreement_error`
（主語動詞の一致）や`incorrect_reference`（代名詞照応）は今回のサンプルでは稀（各2件）だった。

---

## 8. パイプライン品質管理サマリ

- **Analyzer Sub Agent**: 4体（Test C, D, E, F。Test Bはこのレポート作成者が
  Step 2で確定済みの分析をそのままschema変換）。全75問を分析、`taxonomy_issue: true`は0件。
- **Reviewer Sub Agent**: 1体。5ファイル・75問を`GRAMMAR_TAXONOMY.md`の7項目チェックリストに
  照らして横断レビューし、**3件を直接修正**（`structure_test_D.json` Q10, `structure_test_F.json`
  Q6の`primary_target`再分類、`structure_test_E.json` Q9-Aの`error_explanation`からの
  分析者コメント除去）。判断に迷った境界事例（Test C Q2/Q11, Test F Q4/Q1）は既存カテゴリで
  妥当と判断し変更なし。
- **taxonomy_issue件数**: 0件（Analyzer/Reviewerとも`taxonomy_issue: true`を立てた項目はなし）。
  ただしReviewerが`analysis/taxonomy_issues_structure.md`に**1件**、将来のtaxonomy拡張候補
  （比較級/最上級の混同を表す`error_type`の不在）を記録済み。

---

## 9. 出力ファイル一覧

- `analysis/structure_items_all.json` — 統合データセット（75問、taxonomy v1.1 metadata付き）
- `analysis/structure_items_all.csv` — 表形式（Excel/pandas等で扱い可能）
- `analysis/STRUCTURE_ANALYSIS_REPORT.md` — 本レポート
- `analysis/taxonomy_issues_structure.md` — Reviewerが記録したtaxonomy拡張候補（1件、
  `GRAMMAR_TAXONOMY_CHANGELOG.md`で採択・実装済み）
- `analysis/GRAMMAR_TAXONOMY_CHANGELOG.md` — taxonomy v1.0→v1.1の変更履歴と判断基準
- `analysis/raw/structure_test_{B,C,D,E,F}.json` — テスト単位の中間ファイル（Reviewer修正済み、
  taxonomy v1.1反映済み）
