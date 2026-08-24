# Human Review Rubric — TOEFL ITP Grammar Pipeline v1.1 Validation

## Purpose

このrubricは、Validation v1.1のHuman Calibration 46問を、AIのGenerator answer、Reviewer verdict、Solver answer、failure reasonに引きずられず独立評価するためのものです。最初は `human_review_calibration_blind.json` だけを使用してください。答え合わせは判定入力後に `human_review_calibration_key.json` を開きます。

人間の判定を、AI referenceより優先します。AI referenceは論点を揃えるための暫定推定であり、ground truthではありません。

## Review principles

1. Standard written Englishを基準にする。
2. 問題文内の情報だけで解けるかを確認する。外部知識や想像した談話contextを補わない。
3. 「より自然」「より好ましい」だけの差を、確定した文法誤りと数えない。
4. StructureはA–Dを実際に空所へ挿入して、完全な文になる選択肢をすべて確認する。
5. Written Expressionは最初に4つのmarked partのラベルを隠し、文全体にgenuine errorがあるかを確認する。その後、どのpartがerrorかを決める。
6. alternate parse、alternate repair、semantic-only oddity、reference/antecedent dependencyを明示する。
7. answer keyと一致するかではなく、文そのものを判定する。

## Required record for each item

### Q1. Is the item valid?

- `VALID`: TOEFL ITP形式の問題として成立している。
- `INVALID`: 文法的に成立する選択肢がない、誤りがない、または問題形式の前提を満たさない。
- `AMBIGUOUS`: 複数のdefensible answer、複数のparse/repair、context依存などで一意に判定できない。

### Q2. Is there exactly one defensible answer?

- `YES`
- `NO`

Structureでは各選択肢を挿入した全文、Written Expressionでは各marked partを直した全文を比較する。`MARGINAL`な選択肢が一つでも残り、他の解と同程度に成立する場合は`NO`とする。

### Q3. Correct answer

- `A`, `B`, `C`, `D`
- `NONE`: genuine errorが見つからない。
- `AMBIGUOUS`: 複数候補を一意に選べない。

Written Expressionでは、エラーのあるmarked partを答える。文全体が正しい場合は`NONE`とする。

### Q4. English naturalness

1 = 非常に不自然 / 5 = 自然なacademic written English

文法的に成立しているが、語彙や意味の好みだけで少し不自然に感じる場合は、Q1を自動的にINVALIDにしない。コメントに理由を書く。

### Q5. TOEFL ITP style similarity

1 = ITP形式から大きく逸脱 / 5 = ITPのStructure/Written Expressionとして自然

問題がstandaloneで、短いacademic/general-interest contextを持ち、文法中心で解けるかを評価する。

### Q6. Difficulty appropriateness

- `TOO_EASY`
- `APPROPRIATE`
- `TOO_HARD`

語彙の難しさではなく、構文、dependency、error span、distractor confusabilityを基準にする。

### Q7. Main problem if invalid

一つを選ぶ。複数ある場合はcommentにsecondary issueを書く。

- `grammar`
- `ambiguity`
- `semantics`
- `unnatural English`
- `distractor quality`
- `multiple errors`
- `no error`
- `other`

`semantics`は、connector/referenceなどの意味関係が文法誤りとして一意に確定できない場合に使う。`no error`は、全文がstandard written Englishとして成立し、marked errorがない場合に使う。

### Q8. Keep / revise / discard

- `KEEP`: そのまま利用可能。
- `REVISE`: itemの核は利用可能で、局所修正・key修正・context追加で救済可能。
- `DISCARD`: target realizationや本文設計が根本的で、再生成した方が安全。

REJECT相当のitemでも、answer key/target metadataだけの不一致なら`REVISE`を選べる。逆に、clean sentenceに後付けでerrorを入れることがitem設計を壊す場合は`DISCARD`を選ぶ。

## Free-text comment（推奨）

次の形式で短く記録する。

```text
Q1=...; Q2=...; Q3=...; Q4=...; Q5=...; Q6=...; Q7=...; Q8=...
Reason: ...
Alternate parse/repair: ...
```

## Calibration-specific prompts

特に以下をコメントに残してください。

- `batch2-struct-003`: Solverが提案したalternate parseが、元のstemを一語も削除せず成立するか。
- `batch2-struct-004`: Because / Although / Unless / Ifの差が、意味好みだけか、文法的選択制約か。
- `batch2-struct-006`: `tested` / `had been tested`のどちらが、提示contextだけで排除されるか。
- `batch1-we-013`: `It`のantecedent不足を、grammar error、standalone-item invalidity、semantic/context dependencyのどれとして扱うか。
- `batch1-we-007`, `batch1-we-024`: Generator/Reviewerのkeyと、実際の誤りspanのどちらが正しいか。
- Batch 2 clean-sentence REJECT sample: 「一語の誤りを加えれば救える」ことと、現状itemをKEEPできることを分ける。
- `batch3-we-024`: revision後の本文品質と、metadata/difficultyの不整合を別々に評価する。

## Adjudication

最低2名で独立判定し、Q1/Q2/Q3/Q8が一致しないitemだけをadjudication対象にする。多数決で無理にA–Dへ押し込まず、`AMBIGUOUS`または`NONE`を保持する。最終的なv1.2方針は、Human agreementとコメントを根拠に決める。
