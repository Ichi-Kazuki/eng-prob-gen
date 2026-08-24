# Pilot Batch Failure Analysis & Pipeline Hardening Analysis

分析対象: `pilot-2026-08-23` / 40問 Pilot  
作成日: 2026-08-23  
対象: final state が `MANUAL_REVIEW` / `DISCARDED` の3件 + Reviewer round 1 で `REVISE` となった4件  
制約: 本レポートではGenerator prompt、Reviewer prompt、Specification、生成物、DB、サイトを変更していない。

## 1. Executive conclusion

このPilotはパイプライン機構としては完走したが、現状のまま大規模生成へ進める状態ではない。

- final non-accepted は3/40: `pilot-we-002`、`pilot-we-009`、`pilot-we-024`
- 3件ともReviewer round 1 は `PASS` だったため、Reviewer false negative は3件
- 3件のSolver判定（`NONE`×2、`AMBIGUOUS`×1）は、本文の独立文法再評価でも妥当性が高い
- Reviewer round 1 の `REVISE` 4件は、いずれも修正後にReviewer round 2 `PASS`、Solverも一意回答となった
- Generatorの最終失敗はすべてWritten Expressionで発生した。ただし、同一primary_targetの反復ではなく、参照・並列・接続詞という異なる構文にまたがる「一意性・文脈・alternate parse」問題だった
- Specificationの原則（唯一の誤り、二重正解禁止、semantic ambiguity回避）は既に存在する。今回必要なのはSpecificationの全面再設計ではなく、その原則をGenerator/Reviewerの実務チェックへ落とす小修正である

最終推奨は **D. Generator + Reviewerを小修正してvalidation batch** である。100–200問 validation batchを通過するまでは、大規模生成・DB投入・サイト接続へ進めない。

## 2. Pilot baseline

| 指標 | 結果 |
|---|---:|
| Initial generated | 40 |
| Generator schema validation pass | 40/40 |
| Reviewer round 1 PASS | 36/40 |
| Reviewer round 1 REVISE | 4/40 |
| Reviewer round 1 REJECT | 0/40 |
| Solver reached | 40/40 |
| Solver consensus | 37/40 |
| Solver `AMBIGUOUS` | 1 |
| Solver `NONE` | 2 |
| AUTO_ACCEPTED | 37/40 |
| MANUAL_REVIEW | 1 |
| DISCARDED | 2 |

Section差:

- Structure: first-pass 14/15 (93.3%), final accepted 15/15 (100%)
- Written Expression: first-pass 22/25 (88.0%), final accepted 22/25 (88.0%)

この差は n=40 の小標本なので品質率の確定値ではない。ただし、今回の最終失敗3件がすべてWritten Expressionで、Structureのnear-failureはReviewerが事前に止めたという運用上のシグナルはある。

## 3. Candidate inventory and metadata

全対象のGenerator/Reviewer/Solver version hashは同一である。

- Generator: `sha256:ce09d72ff092`
- Reviewer: `sha256:15235bfbb07f`
- Solver: `sha256:df1200bed2b1`
- Spec: `1.0.0`
- Taxonomy: `1.1`

| Candidate | Section | Batch plan target | Original difficulty | Error type / scope | Generation attempt | Revision count | Final state |
|---|---|---|---|---|---:|---:|---|
| `pilot-we-002` | Written Expression | `REFERENCE_AND_DETERMINERS` | EASY | `incorrect_reference` / `clause_level` | 1 | 0 | DISCARDED |
| `pilot-we-009` | Written Expression | `PARALLEL_STRUCTURE` | MEDIUM | `wrong_verb_form` / `sentence_level` | 1 | 0 | MANUAL_REVIEW |
| `pilot-we-024` | Written Expression | `CONNECTORS_CONJUNCTIONS` | EASY | `incorrect_subordinator` / `sentence_level` | 1 | 0 | DISCARDED |
| `pilot-struct-012` | Structure | `VERB_COMPLEMENTATION` | MEDIUM | distractor B / alternate bracketing | 2 | 1 | ACCEPTED |
| `pilot-we-006` | Written Expression | `VERB_COMPLEMENTATION` | EASY | `incorrect_part_of_speech` / `local` | 2 | 1 | ACCEPTED |
| `pilot-we-014` | Written Expression | `NONFINITE_VERB_PHRASES` | EASY | `incorrect_part_of_speech` / `local` | 2 | 1 | ACCEPTED |
| `pilot-we-021` | Written Expression | original plan `CLAUSE_STRUCTURE`; revised target `INVERSION` | EASY → MEDIUM | `missing_required_element` / `clause_level` | 2 | 1 | ACCEPTED |

`pilot-we-021`は、batch plan自体が`CLAUSE_STRUCTURE`だったのに対し、Generator outputが実際には`Not only`による`INVERSION`を実装していた。これはtaxonomyに`INVERSION`が存在しない問題ではなく、既存taxonomyへのalignment失敗である。

## 4. Candidate lifecycle reconstruction

### 4.1 `pilot-we-002` — final `DISCARDED`, `no_valid_answer`

1. **Batch plan**
   - Target: `REFERENCE_AND_DETERMINERS`
   - Subtype: pronoun with no clear antecedent
   - Difficulty: EASY
   - Intended answer position: B
   - Error type/scope: `incorrect_reference` / `clause_level`

2. **Original Generator output**

   Sentence:

   > The observatory recently installed a sophisticated new spectrograph beside its aging telescope, and it will soon rival several professional facilities elsewhere.

   Marked parts:

   - A `recently installed a sophisticated new spectrograph`
   - B `it`
   - C `will soon rival`
   - D `several professional facilities elsewhere`

   Generator intended answer: **B**.  
   Minimal correction: `the new instrument`.

   Generator rationaleは、`it`が`the observatory`、`the spectrograph`、`the telescope`のいずれを指すか不明確だというものだった。

3. **Generator metadata**
   - Attempt 1, revision 0
   - Target/subtype/error metadataはbatch planと一致
   - Schema validationはpass

4. **Reviewer round 1**
   - Verdict: `PASS`
   - Independent answer: **B**
   - `grammar_validity`, `answer_uniqueness`, `target_alignment`等はすべて`PASS`
   - ただしminor issueとして、`it`は統語的には複数の候補を持つものの、`will soon rival several professional facilities`という意味制約から`the observatory`が最も自然に選ばれる、と明記していた
   - ReviewerはdifficultyをMEDIUMとし、GeneratorのEASYと不一致だったが、修正要求にはしなかった

5. **revision_requirements**
   - なし

6. **Revised Generator output**
   - なし

7. **Reviewer round 2**
   - なし

8. **Blinded Solver input**
   - Generator answer、explanation、target、Reviewer output等は除外
   - payload fields: `item_id`, `section`, `sentence`, `marked_parts`
   - sentence/marked partsは上記のOriginal Generator outputと同一

9. **Solver output**
   - Answer: `NONE`
   - Confidence: `HIGH`
   - Reason: 全marked partを含む文は文法的であり、`it`は自然に`the observatory`を指せる
   - `ambiguity_detected: true`

10. **Orchestrator final decision**
    - State history: `GENERATED → REVIEWING → SOLVING → DISCARDED`
    - `solver_answer`がA–Dでない、Generator/Reviewer answerと一致しない、ambiguity flagがtrueのため`DISCARDED`

#### Independent grammar re-evaluation

Solverを無条件に正しいとは扱わず再評価した結果、**Bは標準的な書き言葉として明確な文法誤りではない**と判断する。

- `it`の最有力antecedentは`the observatory`であり、観測所がprofessional facilitiesと競合するという意味は成立する
- `the spectrograph`や`the telescope`の読みは語彙意味上弱いが、弱い候補があることだけで「誤り」にはならない
- この問題は「reference ambiguityを学習させる」問題としては弱く、marked Bをunambiguously erroneousとは言えない
- 問題はmarked part Bそのものの形ではなく、**sentence contextが意図した曖昧性を解消してしまったこと**にある

**Primary root cause:** `GENERATOR_REALIZATION`  
**Secondary root causes:** `REVIEWER_MISSED_NO_ANSWER`, `SPECIFICATION_GAP`

`SPECIFICATION_GAP`は原則の欠如ではなく、reference errorについて「意味制約で一つのantecedentが優勢になった場合はPASS不可」とする運用閾値が未定義という意味である。

### 4.2 `pilot-we-009` — final `MANUAL_REVIEW`, `solver_ambiguous`

1. **Batch plan**
   - Target: `PARALLEL_STRUCTURE`
   - Subtype: parallel verb forms in a list (gerund vs. base form)
   - Difficulty: MEDIUM
   - Intended answer position: A
   - Error type/scope: `wrong_verb_form` / `sentence_level`

2. **Original Generator output**

   > Measuring reaction rates precisely, to control temperature fluctuations, and to record every observation carefully are essential skills for any laboratory chemist.

   Marked parts:

   - A `Measuring reaction rates precisely`
   - B `to control temperature fluctuations`
   - C `and to record every observation carefully`
   - D `are essential skills for any laboratory chemist`

   Generator intended answer: **A**.  
   Minimal correction: `To measure reaction rates precisely`.

3. **Generator metadata**
   - Attempt 1, revision 0
   - Target and error metadataはbatch planと一致
   - Schema validationはpass
   - subtype wordingは`base form`と記載されていたが、実際のB/Cはbare baseではなくto-infinitive

4. **Reviewer round 1**
   - Verdict: `PASS`
   - Independent answer: **A**
   - All checksは`PASS`
   - 指摘はsubtype wording precisionのminor issueのみ

5. **revision_requirements**
   - なし

6. **Revised Generator output**
   - なし

7. **Reviewer round 2**
   - なし

8. **Blinded Solver input**
   - payload fields: `item_id`, `section`, `sentence`, `marked_parts`
   - Generator/Reviewer metadataとcorrect answerは除外
   - sentence/marked partsは上記と同一

9. **Solver output**
   - Answer: `AMBIGUOUS`
   - Confidence: `MEDIUM`
   - Reason: AのgerundとB/Cのto-infinitiveが混在しているため、Aだけを唯一の誤りと分離できない。B/Cを`controlling`/`recording`に直して全体をgerund listにする読みも成立する
   - `ambiguity_detected: true`

10. **Orchestrator final decision**
    - State history: `GENERATED → REVIEWING → SOLVING → MANUAL_REVIEW`
    - SolverがA–Dを一意に返さないため自動採用せず、manual reviewへrouting

#### Independent grammar re-evaluation

この問題には少なくとも次の競合する分析がある。

- **Analysis A:** 3つの非定形要素をto-infinitiveのcoordinate listとして読む。するとAを`To measure`に直す解釈が可能
- **Analysis B:** Aをgerund-participial formとして基準にし、B/Cを`controlling`/`recording`へ正規化する。つまりAが唯一の誤りとは言えず、B/C側にもparallelismの問題が残る

文脈の`essential skills`はlistを示すが、listの基底形をinfinitiveに固定する情報は与えない。したがって、Solverの`AMBIGUOUS`は過剰に厳しいとは言えない。

**Primary root cause:** `GENERATOR_DESIGN`  
**Secondary root causes:** `REVIEWER_MISSED_AMBIGUITY`, `SPECIFICATION_GAP`

これはdistractor単体の問題というより、**一つのmarked errorから複数の全体修正が導かれるcoordinate constructionの設計問題**である。parallel/nonfinite coordinationは、AI生成で再発しやすい危険構文と判断する。

### 4.3 `pilot-we-024` — final `DISCARDED`, `no_valid_answer`

1. **Batch plan**
   - Target: `CONNECTORS_CONJUNCTIONS`
   - Subtype: wrong subordinating conjunction for concessive relation
   - Difficulty: EASY
   - Intended answer position: D
   - Error type/scope: `incorrect_subordinator` / `sentence_level`

2. **Original Generator output**

   > The orchids still failed to bloom on schedule, because the greenhouse maintained nearly ideal humidity and temperature conditions throughout the season.

   Marked parts:

   - A `The orchids`
   - B `still failed`
   - C `to bloom on schedule,`
   - D `because the greenhouse maintained nearly ideal humidity and temperature conditions throughout the season`

   Generator intended answer: **D**.  
   Minimal correction: `although the greenhouse maintained nearly ideal humidity and temperature conditions throughout the season`.

3. **Generator metadata**
   - Attempt 1, revision 0
   - Target/subtype/error metadataはbatch planと一致
   - Schema validationはpass

4. **Reviewer round 1**
   - Verdict: `PASS`
   - Independent answer: **D**
   - All principal checksは`PASS`
   - Minor issueはA/B marked spanが短く、distractor placementがやや弱いという点のみ

5. **revision_requirements**
   - なし

6. **Revised Generator output**
   - なし

7. **Reviewer round 2**
   - なし

8. **Blinded Solver input**
   - payload fields: `item_id`, `section`, `sentence`, `marked_parts`
   - correct answer、minimal correction、target、Reviewer outputは除外
   - sentence/marked partsは上記と同一

9. **Solver output**
   - Answer: `NONE`
   - Confidence: `MEDIUM`
   - Reason: marked partにclear grammatical errorがない。`because` clauseは統語的にwell-formedで、因果関係の妥当性はcontext-dependent
   - `ambiguity_detected: true`

10. **Orchestrator final decision**
    - State history: `GENERATED → REVIEWING → SOLVING → DISCARDED`
    - Solverが一意のerror positionを返さないため`DISCARDED`

#### Independent grammar re-evaluation

Solverの`NONE`は妥当である。

- Dの`because`は完全なbecause-clauseを導入しており、構文上の誤りはない
- 「良好な温湿度条件なのに開花しなかった」という状況は、因果的説明として不自然・疑わしいかもしれないが、truth-valueや因果主張の不自然さはそれ自体で文法誤りにはならない
- `although`は意味上の意図には合うが、Dを標準英語から排除するgrammar-only evidenceにはなっていない
- よって、問題はmarked Dではなく、**semantic contrastをsyntactic/grammatical errorとして実装したsentence design**にある

**Primary root cause:** `GENERATOR_REALIZATION`  
**Secondary root causes:** `REVIEWER_MISSED_NO_ANSWER`, `SPECIFICATION_GAP`

`SOLVER_OVERSTRICT`は付与しない。Solverは「因果関係が好ましくないから」ではなく、「文法的な誤りが0件」と判定しており、独立再評価もこれを支持する。

## 5. Reviewer round 1 `REVISE` 4件

### 5.1 `pilot-struct-012` — distractor alternate bracketing

**Initial lifecycle**

- Batch plan: `VERB_COMPLEMENTATION`, `make + object + adjective complement`, MEDIUM, answer D
- Original stem: `City planners hope that wider sidewalks and dedicated bike lanes will make the downtown corridor ___.`
- Original options:
  - A `more accessibility for pedestrians and cyclists alike`
  - B `for pedestrians and cyclists alike more accessible`
  - C `accessible pedestrians and cyclists alike`
  - D `more accessible for pedestrians and cyclists alike`
- Original Generator answer: D
- Reviewer round 1: `REVISE`, independent answer D
- Revision requirement: Bの`for pedestrians and cyclists alike`が`the downtown corridor`のpostnominal modifierになり、`make [the downtown corridor for pedestrians and cyclists alike] [more accessible]`というalternate valid parseを作らないようにする

**Revision and lifecycle continuation**

- Revised B: `for pedestrians and cyclists alike accessible more`
- A/C/Dは維持、correct answerはDのまま
- Reviewer round 2: `PASS`, independent answer D
- Blinded Solver input: `stem`, `options`, `item_id`, `section`のみ。correct answer/rationalesは除外
- Solver: D / HIGH; `make` + adjective complementが成立し、他の選択肢はword form/order不足
- Final: `ACCEPTED`

**Independent assessment:** 実質的に改善された。改訂Bは通常のconstituent bracketingでfully grammaticalな読みを提供しない。Reviewerを表面的に満足させただけではなく、元の二重bracketingを除去している。

**Root cause:** primary `GENERATOR_DESIGN`（PP attachmentを許すword-order distractor設計）  
**Recurrence risk:** MEDIUM–HIGH。名詞直後に置くPPをword-order distractorへ再利用すると再発しやすい。

### 5.2 `pilot-we-006` — `feel isolation` was already grammatical

**Initial lifecycle**

- Batch plan: `VERB_COMPLEMENTATION`, predicate adjective after linking verb, EASY, answer B
- Original sentence: `Sociologists have found that prolonged unemployment often leaves individuals feeling isolation from their communities and support networks.`
- B: `often leaves individuals feeling isolation`
- Intended correction: `often leaves individuals feeling isolated`
- Reviewer round 1: `REVISE`, independent answer `NONE`, critical failure
- Reviewer reason: `feel`はlinking verbとしてpredicate adjectiveを取れる一方、transitive verbとしてabstract noun objectも取れる。`feeling isolation`はstandard written Englishであり、genuine errorがない

**Revision and lifecycle continuation**

- Generator changed `feel` construction to: `Sociologists have found that prolonged unemployment often causes individuals to become isolation from their communities and support networks.`
- Revised B: `often causes individuals to become isolation`
- Correction: `often causes individuals to become isolated`
- Reviewer round 2: `PASS`, independent answer B
- Blinded Solver input: revised `sentence` + four `marked_parts` + `item_id`/`section`のみ
- Solver: B / HIGH; `become` requires an adjective complement in this use
- Final: `ACCEPTED`

**Independent assessment:** 改善は実質的である。bare abstract noun `isolation`を`become`のcomplementに置く読みは通常の標準英語では成立せず、Bに唯一のerrorが生じた。これは`feel`を含むlexical frameの選択が原因であり、単なる説明文の書き換えではない。

**Root cause:** primary `GENERATOR_REALIZATION`（verb subcategorizationの見落とし）  
**Secondary:** operational `SPECIFICATION_GAP`（linking/perception verbごとのcomplement-frame guardがない）  
**Recurrence risk:** HIGH。`feel`, `leave`, `find`などのperception/causative frameで同型が繰り返され得る。

### 5.3 `pilot-we-014` — ordinal + `-ing` alternate parse

**Initial lifecycle**

- Batch plan: `NONFINITE_VERB_PHRASES`, ordinal/superlative + infinitive, EASY, answer B
- Original sentence: `The young volcanologist was the first researcher studying the mountain's seismic tremors continuously, an effort that greatly improved eruption forecasting methods.`
- B: `was the first researcher studying the mountain's seismic tremors continuously`
- Intended correction: `was the first researcher to study ...`
- Reviewer round 1: `REVISE`, independent answer B
- Reviewer reason: Bは`the first researcher [who was] studying ...`というreduced-relative parseでもfully grammatical。appositiveがachievement readingをbiasするが、alternate parseは実在する

**Revision and lifecycle continuation**

- Revised sentence: `The young volcanologist was the first researcher ever identifying the mountain's seismic pattern for eruption forecasting.`
- Revised B: `was the first researcher ever identifying the mountain's seismic pattern`
- Correction: `was the first researcher ever to identify the mountain's seismic pattern`
- Reviewer round 2: `PASS`, independent answer B
- Blinded Solver input: revised `sentence` + four `marked_parts` + `item_id`/`section`のみ
- Solver: B / HIGH; `the first researcher ever`のachievement complementとして`to identify`が必要
- Final: `ACCEPTED`

**Independent assessment:** 修正後は、通常のedited-English readingではachievement interpretationが支配的となり、元のreduced-relative readingは競合解釈として十分強くない。したがって表面的修正ではなく改善と認定する。ただし、ordinal + participleは引き続き危険構文なのでregression fixtureに残す。

**Root cause:** primary `GENERATOR_DESIGN`（ordinal + participleのintrinsic alternate parse）  
**Secondary:** `GENERATOR_REALIZATION`（appositive/contextが曖昧性を十分に排除しなかった）  
**Recurrence risk:** MEDIUM。構文が限定的だが、`first/last/only + NP + -ing`のようなテンプレートで再発可能。

### 5.4 `pilot-we-021` — primary target mismatch

**Initial lifecycle**

- Batch plan target: `CLAUSE_STRUCTURE`, subtype `missing required correlative element in a compound predicate`, EASY
- Original sentence: `Not only ethnomusicologists study traditional instruments but also examine the cultural contexts in which they are played.`
- Intended correction: `Not only do ethnomusicologists study traditional instruments ...`
- Original metadata: `primary_target=CLAUSE_STRUCTURE`
- Reviewer round 1: `REVISE`, independent answer A
- Reviewer reason: actual issue is fronted-negative `Not only` triggering subject–auxiliary inversion. Taxonomy explicitly assigns this to `INVERSION`; the independent clause itself is well-formed

**Revision and lifecycle continuation**

- Textは変更せず、`primary_target`を`INVERSION`へ変更
- Subtypeを`subject-auxiliary inversion after a fronted negative correlative ('Not only')`へ変更
- `tested_error_type=missing_required_element`は維持
- DifficultyをEASYからMEDIUMへ整合
- Reviewer round 2: `PASS`, independent answer A
- Blinded Solver input: sentence/marked partsのみ
- Solver: A / HIGH; fronted `Not only` requires inversion
- Final: `ACCEPTED`

**Independent assessment:** 実質的な改善。本文の文法問題を変えず、metadataが実際のtested phenomenonと一致した。taxonomyに新カテゴリを追加する必要はない。

**Root cause:** primary `GENERATOR_REALIZATION`（batch planのtargetと実際の構文のalignment失敗）  
**Taxonomy gap判定:** `TAXONOMY_GAP`は付与しない。`INVERSION`は既存taxonomyにあり、今回の問題はcategoryの不存在ではなく誤routingである。  
**Recurrence risk:** MEDIUM。`Not only`, `Not until`, fronted negative/place adverbialの計画時に再発可能。

## 6. Root cause classification and recurrence risk

| Root cause | Pilot evidence | Recurrence risk | Assessment |
|---|---|---|---|
| `GENERATOR_DESIGN` | WE-009のmixed nonfinite coordination、S-012のPP attachment、WE-014のordinal + participle | HIGH overall | 同じテンプレート/構文を使えば繰り返し発生し得る。構文ごとの候補制限が必要 |
| `GENERATOR_REALIZATION` | WE-002のsemantic resolution、WE-024のsemantic connector、WE-006の`feel + noun`、WE-021のtarget mismatch | HIGH | planは存在していても、実現文・lexical frame・metadataで一意性が壊れる |
| `REVIEWER_MISSED_AMBIGUITY` | WE-009をPASS。S-012/WE-014と同系統のalternate parseを一貫して止められていない | HIGH | `answer_uniqueness`が最終回答一致に引っ張られ、競合parse/repair setを列挙し切れていない |
| `REVIEWER_MISSED_NO_ANSWER` | WE-002、WE-024をPASSしたがSolverはNONE | HIGH | full-sentence auditが「標準英語として許容か」と「Generatorの狙い」を分離できていない |
| `REVIEWER_TARGET_ANALYSIS` | 今回のReviewerはWE-021を正しく検出 | LOW | 今回は根因ではない。target alignmentチェックは機能している |
| `REVISION_REGRESSION` | 4件すべて修正後PASS、Solverも一意、別エラーの証拠なし | LOW | 今Pilotでは観測なし。次batchでfixture監視は必要 |
| `SPECIFICATION_GAP` | 原則はあるが、reference/connector/coordination/lexical frameのoperational thresholdがない | MEDIUM | 全面改訂は不要。fixtureと判断基準の追記が有効 |
| `TAXONOMY_GAP` | WE-021は`INVERSION`が既存。未分類カテゴリではない | LOW | 今回の根因としては不採用 |
| `SOLVER_OVERSTRICT` | NONE×2、AMBIGUOUS×1を独立再評価が支持 | LOW | Solverを緩める根拠はない |
| `OTHER` | 該当なし | LOW | — |

## 7. Reviewer false-negative analysis

### Count

**3件**（`pilot-we-002`, `pilot-we-009`, `pilot-we-024`）。  
これは initial 40件中3件、Solver-reached 40件中3件（7.5%）である。

### Failure mode別

| Candidate | Reviewer PASSの内容 | 独立再評価 | False-negative type |
|---|---|---|---|
| WE-002 | Bを独立answerとして採用。semantic resolutionによる弱い曖昧性はminor扱い | genuine grammatical errorなし | Missed no-answer / reference ambiguity |
| WE-009 | Aを独立answerとして採用。mixed listのalternate normalizationを未検出 | unique marked errorではない | Missed ambiguity |
| WE-024 | Dのcontrast intentをgrammatical errorとして受容 | `because` clauseは文法的 | Missed no-answer / semantic-vs-grammar confusion |

### 強化対象

- **answer uniqueness audit:** Generator answerとの一致後に、回答を裏付けるのではなく、すべてのmarked partの`ACCEPTABLE/ERROR/MARGINAL`を再列挙する必要がある
- **all-options / all-marked-parts validation:** WEでは「唯一のerror」を判定する前に、各partを直した場合の修正文と、sentence全体の残存errorを比較する必要がある
- **full-sentence audit:** 「狙った意味に合わない」ことと「標準英語の文法誤り」を分離する。WE-024のようなbecause/althoughはここが重要
- **alternate parse detection:** reduced relative、PP attachment、mixed gerund/to-infinitive coordinationを重点fixture化する

今回3件だけなのでReviewer全体の大規模redesignを正当化する標本ではない。ただし、3件すべてがReviewer PASSを通ったため、次batch前のfocused hardeningは必須である。

## 8. Generator failure pattern

### 8.1 Planning dimensions

最終3失敗の共通点は以下である。

- primary_targetは3件とも異なる: `REFERENCE_AND_DETERMINERS`, `PARALLEL_STRUCTURE`, `CONNECTORS_CONJUNCTIONS`
- difficultyはEASY, MEDIUM, EASY。HARD itemに限定されない
- sentence lengthは20–24語、clause countはすべて2相当で、Pilotの中心帯にある
- error_scopeは`clause_level`または`sentence_level`で、local typo型ではない
- schema、target、subtype、error_type、error_scopeというmetadataは機械的には妥当だった

したがって、単一カテゴリの故障ではなく、**文脈依存の一意性、意味と文法の境界、複数の構文解析が可能なsentence design**が共通patternである。

### 8.2 Written Expression固有か

「最終失敗3件がすべてWE」であることは、WE固有の生成リスクを示す。ただし、primary_targetが同一ではないため、`REFERENCE_AND_DETERMINERS`等の単一カテゴリ故障とは言えない。

WEでは、完全なsentenceの中に一つだけerrorを埋める必要がある。そのため、次のような誤差がStructureより起こりやすい。

1. 文法的には成立するが、意味・談話上だけ不自然な表現をerrorとしてしまう（WE-002, WE-024）
2. 文全体を複数のparse/repair strategyで正規化できる（WE-009, WE-014）
3. lexical subcategorizationが狙いと異なる（WE-006）
4. 本文が正しくてもmetadataだけが別targetになる（WE-021）

### 8.3 Structureとの差

Structure 15件は1件のnear-failure（S-012）をReviewerが初回で検出し、最終15/15になった。S-012はdistractor Bのalternate bracketingという局所的問題で、ReviewerのStructure answer-uniqueness auditが機能した。

一方、WE 25件では3件がReviewer PASSを通過したまま、Solverで2件NONE、1件AMBIGUOUSになり、最終22/25となった。これはWEの「一つのmarked errorだけを作る」要件が、現在のGenerator/Reviewerにとってより脆弱であることを示す。

ただし、n=15/25の小標本であり、これを長期的なsection failure rateとは解釈しない。

## 9. Improvement recommendations

### P0 — 大規模生成前に必須

| Owner | Recommendation | 種別 |
|---|---|---|
| Generator | WEのreference errorは、semantic selectional preferenceで一つのantecedentが優勢になる文を避ける。意図するambiguityが標準英語のerrorとして立たない場合は生成候補にしない | Generator change |
| Generator | WE connector errorは、単なる「因果関係が好ましくない」だけでなく、文内のsyntax/complement frameで一意に排除できる構成を優先する。because/althoughのように両方が統語的に可能なsentenceは重点審査対象にする | Generator change |
| Generator | mixed gerund/to-infinitive list、ordinal + `-ing`、PP attachmentを伴うword-order distractor、`feel + abstract noun`を危険templateとして扱う | Generator change |
| Generator/Orchestrator | batch planの`primary_target`と実際の構文を出力後に突合する。特にfronted negative inversionは`INVERSION`へ明示的にroutingする | Orchestrator change |
| Reviewer | WEで`NONE`相当（genuine error=0）、複数parse、複数repair strategy、marked spanのstandard-English許容を検出したら`PASS`禁止。Generator answer一致は救済理由にしない | Reviewer change |
| Reviewer | focused alternate-parse auditを追加対象にする: reduced relative、PP attachment、nonfinite coordination、semantic-vs-grammar connector、lexical complement frame | Reviewer change |
| Orchestrator | Solver `NONE/AMBIGUOUS`を自動採用しない現行gateは維持する。これは今回3件をcontainできており、全面的なrouting変更は不要 | No change |
| Solver | NONE/AMBIGUOUSを無理にA–Dへforceしない現行仕様を維持する | No change |
| Specification | Hard ruleの全面変更はしない。現行specは唯一性・二重正解禁止・semantic ambiguity回避を既に要求している | No change |

### P1 — 次のvalidation batch前に推奨

| Owner | Recommendation | 種別 |
|---|---|---|
| Reviewer | 本レポートの7 fixtureを使い、期待 verdict/independent answer/solver outcomeを固定したfocused adversarial validationを行う | Reviewer change |
| Generator | `feel`等のverb-frame、ordinal + participle、pronoun antecedent、connector relation、parallel listについて、安全なtemplateと禁止/要追加監査templateを分ける | Generator change |
| Specification | `incorrect_reference`、`incorrect_subordinator`、parallelismの「文法誤りと意味の不自然さの境界」、およびalternate parseの扱いを運用例として追記する | Spec change |
| Orchestrator | validation batchのstop metricsに、`Reviewer PASS → Solver NONE/AMBIGUOUS`、`final non-accepted`、`revision regression`を明示する。閾値超過時はmass generationへ進めない | Orchestrator change |
| Reviewer/Orchestrator | `REVISE 4/4`を成功率だけでなく、revision後の独立Solver一致・full-sentence再監査・metadata整合性で確認する | Reviewer/Orchestrator change |

### P2 — 将来的改善

| Owner | Recommendation | 種別 |
|---|---|---|
| Generator/Reviewer | constituency/attachment候補やverb complement frameを検査できるgrammar-aware lintを導入する | Generator + Reviewer change |
| Reviewer | 独立Reviewer 2名または人手calibration sampleを導入し、semantic ambiguityの判定基準を測定する | Reviewer change |
| Spec/Taxonomy | 同型failureが複数batchで再発した場合のみ、taxonomy promotion/holdout見直しを検討する | Spec change |
| Orchestrator | failure signatureごとの累積再発率・template別acceptanceを記録し、危険templateを自動的にvalidation-onlyへ隔離する | Orchestrator change |

## 10. Regression fixtures

P0 fixtureとして、failure 3件は必ず保持する。さらに、Reviewerが初回に正しく検出した有用なREVISE例も、originalとrevisedをpairで保持する。

| Fixture | Type | Expected behavior |
|---|---|---|
| `pilot-we-002` | no valid answer / pronoun semantic resolution | ReviewerはPASS不可。Solver=`NONE`, `ambiguity_detected=true` |
| `pilot-we-009` | alternate parse / mixed nonfinite coordination | ReviewerはPASS不可。Solver=`AMBIGUOUS` |
| `pilot-we-024` | no valid answer / semantic connector mistaken for grammar | ReviewerはPASS不可。Solver=`NONE` |
| `pilot-struct-012` original | distractor PP alternate bracketing | Reviewer=`REVISE`; Bを代替valid parseとして説明できる |
| `pilot-struct-012` revised | repaired Structure distractor | Reviewer=`PASS`; Solver=D |
| `pilot-we-006` original | lexical complement frame | Reviewer=`REVISE`; independent answer=`NONE` |
| `pilot-we-006` revised | unambiguous `become + adjective` frame | Reviewer=`PASS`; Solver=B |
| `pilot-we-014` original | ordinal + reduced-relative ambiguity | Reviewer=`REVISE`; B alternate parseを指摘 |
| `pilot-we-014` revised | context-strengthened ordinal construction | Reviewer=`PASS`; Solver=B |
| `pilot-we-021` original | target metadata mismatch | Reviewer=`REVISE`; target=`INVERSION`を要求 |
| `pilot-we-021` revised | corrected target metadata | Reviewer=`PASS`; Solver=A |

このうち、`pilot-we-002`、`pilot-we-009`、`pilot-we-024`は、将来Generator/Reviewerを更新した際に同じ型の問題を通さないための必須回帰fixtureである。

## 11. Readiness recommendation

### 推奨: **D. Generator + Reviewerを小修正してvalidation batch**

根拠:

1. Generator側には、WEのsentence designで、semantic-only error・lexical frame・alternate parse・parallel normalizationを許してしまう再発可能な問題がある
2. Reviewer側には、今回3件のfalse negativeがあり、full-sentence audit / answer uniqueness auditを強化する必要がある
3. Orchestrator/Solverは、`NONE/AMBIGUOUS`を自動採用せずmanual/discardへ送る点で機能している
4. Specificationの基本原則は妥当であり、taxonomyも`INVERSION`を既に含むため、Specificationからの全面再検討（E）までは不要
5. 4件のREVISEは4/4で実質改善されたため、現在のrevision loopは活用できる

推奨順序:

1. このレポートのP0に相当するGenerator/Reviewerのfocused hardeningを設計する
2. 7 fixtureでfocused validationを行う
3. 100–200問 validation batchを実施する
4. Reviewer false-negative、Solver NONE/AMBIGUOUS、revision regressionを確認してから、mass generationの可否を再判定する

## 12. Source artifacts checked

必須artifact:

- `analysis/pilot/PILOT_BATCH_REPORT.md`
- `analysis/pilot/pilot_batch_plan.json`
- `analysis/pilot/pilot_initial_items.json`
- `analysis/pilot/pilot_provenance.json`
- `analysis/pilot/pilot_accepted_items.json`
- `analysis/pilot/pilot_manual_review.json`
- `analysis/pilot/pilot_failure_items.json`
- `analysis/pilot/pilot_metrics.json`

関連artifact/定義:

- `.claude/agents/toefl-itp-grammar-generator.md`
- `.claude/agents/toefl-itp-grammar-reviewer.md`
- `.claude/agents/toefl-itp-grammar-solver.md`
- `specs/TOEFL_ITP_GRAMMAR_SPEC.md`
- `specs/toefl_itp_grammar_spec.json`

この分析ファイル作成以外の実装変更は行っていない。
