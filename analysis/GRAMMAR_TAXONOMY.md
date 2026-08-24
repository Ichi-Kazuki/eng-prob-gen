# TOEFL ITP Structure — Grammar Taxonomy

## 目的

`itp_structure_item_specs_testB.json` の `grammar_target` は問題ごとに粒度がバラバラで
（例: "subject complement" のような統語論的カテゴリと "existential 'there is/are' construction"
のような構文名が同じ階層に混在）、複数テストを横断して集計・比較したり、新規問題生成のテンプレートとして
使うには不安定だった。

本taxonomyはこれを3階層に整理する。

```
primary_target   ← 安定した大分類（10〜15個、クローズドセット / 増やさない）
subtype          ← 出題される具体的な構文（primary_target内で自由に追加してよい）
secondary_features ← 主目的ではないが問題文中に同居する副次的な文法現象（自由記述タグの配列）
```

- **primary_target** は今後すべてのTOEFL ITP Structure問題（Test B〜Fやその他の公式問題）を
  分類するための固定カテゴリ。新しい問題を分析していて既存14個のどれにも当てはまらない場合は、
  安易に15個目を作らず、まず「どのprimary_targetのsubtypeとして表現できるか」を検討すること。
- **subtype** は出題構文そのもの（例: "adjective + enough + to-infinitive result construction"）。
  同じprimary_target内でいくつ増えても構わない。
- **secondary_features** はその問題の主眼ではないが、文中に同時に存在する文法現象
  （縮小関係詞節、省略、並列構造、時制など）を自由記述の配列で記録する。ここに書かれた現象が
  将来的に頻出するようになれば、それ自体を独立したsubtype/primary_targetに格上げすることを検討する。

## primary_target 一覧（15カテゴリ）

| id | 日本語ラベル | 説明 | 典型的な出題形式 |
|---|---|---|---|
| `CLAUSE_STRUCTURE` | 節構造・文断片 | 独立節（主語+定形動詞）が成立しているか。文断片・接続過多を見抜く問題。主語動詞の一致もここに含む。 | 文頭の空所に「主語+動詞」を要求し、名詞節化・関係詞化・不定詞化された誤答と対比させる |
| `NOUN_CLAUSES` | 名詞節 | that節・間接疑問文（wh-語）が主語/目的語/補語として機能する構造。語順（倒置なし）が焦点になることが多い。 | "what/whether/that + S + V" の語順を問う |
| `RELATIVE_CLAUSES` | 関係詞節 | 制限/非制限関係詞節、関係代名詞の格・省略、関係詞節内の並列構造。 | 非制限用法のコンマ関係詞節内で先行動詞と並列させる |
| `ADVERBIAL_CLAUSES` | 副詞節の構造 | 時・理由・譲歩・条件・目的を表す従属節「そのものの内部構造」（節 vs 句 vs 倒置形の判別）。接続詞の語彙選択が焦点の場合は `CONNECTORS_CONJUNCTIONS` を使う。 | "when + S + V" のような完全な節を、名詞句・分詞句・疑問形と区別させる |
| `CONNECTORS_CONJUNCTIONS` | 接続語彙の選択 | 前置詞 vs 接続詞、原因・対比・比較・逆接など論理関係を表す語彙そのものの選択。ディレクションのExample I（due to / because / in spite of / regardless of）が典型例。動詞・形容詞・分詞が特定の前置詞を要求するコロケーション（下記`WORD_CLASS_FORM`ではなく前置詞選択そのものが焦点の場合）のうち、特定の語に支配されない独立した前置詞・接続語句の対比もここに含む。 | 4つの接続表現から文脈に合う1つを選ぶ |
| `VERB_FORM_VOICE` | 定形動詞の時制・態 | 定形動詞（主節・従属節の本動詞）の時制・相・能動/受動の選択。非定形（分詞・不定詞・動名詞）の形の選択は `NONFINITE_VERB_PHRASES` を使う。 | 文中の唯一の定形動詞スロットで時制/態を問う |
| `VERB_COMPLEMENTATION` | 動詞の補語構造 | be動詞などの連結動詞に続く主格補語、使役動詞・知覚動詞に続く目的格補語の構造。特定の動詞・分詞・形容詞が支配する前置詞コロケーション（"benefit from," "associated with," "known for" 等）もここに含む（前置詞選択が動詞・分詞・形容詞という特定の語に支配されている場合）。 | "make + O + 形容詞" や "is + 名詞句" の補語選択、"benefit from" の前置詞選択 |
| `NONFINITE_VERB_PHRASES` | 非定形動詞句 | 分詞（縮小関係詞節・結果分詞）、不定詞（目的・序数修飾）、動名詞など、定形動詞を持たない修飾句の形の選択。 | 名詞を修飾する過去分詞/現在分詞/不定詞の選択、"the first ... to V" |
| `COMPARATIVES_DEGREE` | 比較・程度構文 | 比較級・最上級、enough/so/too/as...asなどの程度構文。比較級と最上級の混同、および"so...that"必須の結果節に"very"を誤用するなどの程度・強意語選択の誤りもここに含む。 | "形容詞 + enough + to V" の完成 |
| `PARALLEL_STRUCTURE` | 並列構造 | 等位接続詞・相関接続詞（and, or, both...and, not only...but also）で結ばれる要素間の統語的並行性。 | リスト列挙や2要素比較での品詞・時制の一致 |
| `WORD_ORDER_MODIFICATION` | 語順・修飾語配置 | 形容詞句・同格句・分詞構文などの名詞修飾要素の内部語順。名詞句そのものの構造。 | 同格句の語順、"名詞+形容詞+前置詞句" の並べ替え型誤答 |
| `INVERSION` | 倒置構文 | 否定副詞句・場所句・条件節の省略形などが文頭に来た際の主語・助動詞倒置。 | "Not until..." "Only after..." に続く倒置節の完成 |
| `EXISTENTIAL_EXPLETIVE` | 存在構文 | there is/are、it is などの形式主語・虚辞構文。 | "There are + 名詞句" の完成、"They/The" などの誤答との対比 |
| `REFERENCE_AND_DETERMINERS` | 照応・限定詞 | 代名詞の照応・一致、冠詞・数量詞（much/many, few/little, every/each）、可算/不可算の選択。 | 先行詞のない代名詞、限定詞のみの誤答選択肢 |
| `WORD_CLASS_FORM` | 品詞選択・派生形 | ある統語スロット（名詞句内の修飾語、名詞句の主要部、動詞を修飾する副詞的要素、節の主語など）が要求する派生形・品詞（形容詞/副詞/名詞/動詞のいずれか）の選択。語順そのもの（`WORD_ORDER_MODIFICATION`）、動詞が要求する補語構造（`VERB_COMPLEMENTATION`）、節の成立可否（`CLAUSE_STRUCTURE`）とは異なり、「その位置にどの品詞・派生形の単語が入るべきか」自体が焦点となる問題に使う。 | "recent surge" vs "recently surge"（形容詞 vs 副詞）、"listener of" vs "listen of"（名詞 vs 動詞）、"Heat expands" vs "Hot expands"（名詞 vs 形容詞、主語位置） |

> 15個は事実上の上限。ETSの公式問題集で頻出する統語論的トピックをすべて収める設計。
> 今後の分析で「どのカテゴリにも自然に入らない」問題が複数出た場合のみ、追加を検討する
> （目安: 同じ現象が3問以上・複数のPractice Testで繰り返し観測され、既存カテゴリのsubtypeとして
> 吸収すると定義上の意味が歪む場合のみ新設する。詳細な判断基準は
> `GRAMMAR_TAXONOMY_CHANGELOG.md` を参照）。

## primary_target 判定ガイド（曖昧なケースの切り分け）

- **節 vs 語彙**: 副詞節の内部構造（時制・語順・節 vs 句）が焦点 → `ADVERBIAL_CLAUSES`。
  「どの接続語彙が意味的に正しいか」（前置詞か接続詞か、原因か対比か）が焦点 → `CONNECTORS_CONJUNCTIONS`。
- **定形 vs 非定形**: 空所が文の唯一の本動詞（定形）になる → `VERB_FORM_VOICE` か `CLAUSE_STRUCTURE`
  （節として成立するかどうかが焦点なら`CLAUSE_STRUCTURE`、時制/態の選択が焦点なら`VERB_FORM_VOICE`）。
  空所が名詞を修飾する分詞・不定詞など非定形要素 → `NONFINITE_VERB_PHRASES`。
- **関係詞節 vs 非定形修飾句**: 関係代名詞が明示的に残るか、関係詞節としての並列構造が焦点 →
  `RELATIVE_CLAUSES`。関係代名詞が縮約されて分詞だけが残る（"that were provided" → "provided"）形の
  選択が焦点 → `NONFINITE_VERB_PHRASES`（secondary_featuresに "reduced from relative clause" と記録）。
- **補語 vs 語順**: 動詞の後に何が来るべきか（品詞・格）が焦点 → `VERB_COMPLEMENTATION`。
  名詞句内部の要素の並べ替えが焦点 → `WORD_ORDER_MODIFICATION`。
- **品詞選択 vs 語順 vs 補語 vs 節構造**: 名詞句内の1語が「正しい位置にあるが品詞が違う」
  （"recent" vs "recently"、"listener" vs "listen"）→ `WORD_CLASS_FORM`（語順は問題ない。
  品詞・派生形だけが焦点）。同じ「1語の品詞違い」でも、動詞を修飾する副詞的要素の位置
  （述語補語スロットではない）→ `WORD_CLASS_FORM`。節の主語スロットに名詞ではなく形容詞が
  誤って置かれる（"Heat expands" vs "Hot expands"）→ `WORD_CLASS_FORM`。一方、動詞の直後の
  補語スロット自体に何を置くか（名詞句か形容詞句か）が焦点なら `VERB_COMPLEMENTATION`、
  名詞句内の要素の並び順そのものが焦点なら `WORD_ORDER_MODIFICATION`。
- **前置詞コロケーション**: 特定の動詞・分詞・形容詞が支配する固定的な前置詞選択
  （"benefit from," "known for," "rich in"）→ `VERB_COMPLEMENTATION`（該当語に支配された
  コロケーションとして扱う）。支配語を伴わない独立した前置詞・接続語句どうしの対比
  （"beside" vs "between," "during...until" vs "from...until"）→ `CONNECTORS_CONJUNCTIONS`。
  `tested_error_type`は両者とも`wrong_preposition_collocation`を使う（下記error_type一覧参照）。

## error_type / tested_error_type 一覧（15値、固定語彙）

Structure（`distractors.*.error_type`）とWritten Expression（`error_span.tested_error_type`）の
両方で共有される、誤答・誤りの「メカニズム」を表す固定語彙。`primary_target`が「どの文法トピックを
テストしているか」を表すのに対し、この語彙は「その誤答/誤りが構造的にどう間違っているか」を表す。
この語彙もクローズドセットであり、いずれの値にも当てはまらない場合はもっとも近い値を選び、
`taxonomy_issue: true` と理由を記録すること（安易に16個目を作らない）。

| id | 説明 |
|---|---|
| `wrong_verb_form` | 動詞の時制・相・形（原形/-ing/-ed等）の誤り |
| `wrong_voice` | 能動/受動の誤り |
| `missing_required_element` | 文・節・句の成立に必要な要素（主語・動詞・接続詞等）が欠落している |
| `extraneous_element` | 不要な要素（余分な語・重複した語）が追加されている |
| `wrong_word_order` | 要素は揃っているが並び順が誤っている |
| `incorrect_subordinator` | 従属接続詞の選択が誤っている（意味関係・統語的要求に合わない） |
| `incorrect_relative_marker` | 関係詞（who/whom/which/that/whose等）の選択・格が誤っている |
| `fragment` | 節として成立していない（定形動詞や主語が欠けている断片） |
| `double_subject` | 主語が重複している（例: 関係代名詞と再帰的な代名詞の重複） |
| `agreement_error` | 主語動詞の数の一致、または名詞と数量詞の一致の誤り |
| `wrong_complementation` | 動詞・連結動詞が要求する補語構造（品詞・句のタイプ）が誤っている（前置詞コロケーションの誤りは含まない。`wrong_preposition_collocation`を参照） |
| `incorrect_part_of_speech` | 単語の品詞そのものが誤っている（比較級/最上級の混同は含まない。`wrong_degree_form`を参照） |
| `incorrect_reference` | 代名詞の照応先が不明・不適切 |
| `wrong_preposition_collocation` | 動詞・分詞・形容詞・名詞が要求する固定的な前置詞コロケーション、または支配語を伴わない前置詞・接続語句どうしの対比における選択の誤り（例: "benefit from" vs "benefit of," "beside" vs "between"）。品詞そのもの・補語構造そのものの誤りではなく、語彙的に固定された前置詞の選択の誤り。 |
| `wrong_degree_form` | 比較級・最上級・原級の混同（例: "the greater" とすべき箇所に最上級を使う）、または"so...that"のように後続の結果節等を要求する程度・強意語の選択の誤り（例: "so" とすべき箇所に "very" を使う） |

> **語彙拡張履歴**: `wrong_preposition_collocation` と `wrong_degree_form` は Written Expression
> フェーズのtaxonomy gap精査（2026-08-23）で追加された。詳細は`GRAMMAR_TAXONOMY_CHANGELOG.md`を参照。

## secondary_features の記法

自由記述の英語短文タグを配列で記録する。よく使うタグの例:

- `"ellipsis"` — 省略構文（"as [it does] on..."）
- `"reduced from relative clause"` — 分詞句が関係詞節の縮約であることの明示
- `"parallel structure with coordinate verb"` — 等位動詞との並列
- `"passive voice"` / `"active voice"`
- `"resumptive pronoun error"` — 関係代名詞と重複する代名詞
- `"appositive phrase"`
- `"infinitive of purpose"`
- `"past perfect tense"`
- 該当なしの場合は空配列 `[]`

## Test B（Q1〜15）の新taxonomyへの再分類サマリ

| Q# | primary_target | subtype |
|---|---|---|
| 1 | VERB_COMPLEMENTATION | predicate nominative after linking verb (be + NP) |
| 2 | COMPARATIVES_DEGREE | adjective + enough + to-infinitive result construction |
| 3 | NOUN_CLAUSES | embedded question (wh-word) word order |
| 4 | VERB_COMPLEMENTATION | object complement after causative verb (make + O + Adj) |
| 5 | CLAUSE_STRUCTURE | main clause (subject + finite verb) identification |
| 6 | RELATIVE_CLAUSES | non-restrictive relative clause with parallel coordinate predicate |
| 7 | WORD_ORDER_MODIFICATION | appositive noun phrase placement and internal word order |
| 8 | ADVERBIAL_CLAUSES | time clause introduced by "when" |
| 9 | CONNECTORS_CONJUNCTIONS | elliptical comparative connector "as" vs. subordinator/adverb |
| 10 | NONFINITE_VERB_PHRASES | reduced passive relative clause (past participle modifying noun) |
| 11 | NONFINITE_VERB_PHRASES | participial phrase of result ("thereby" + -ing) |
| 12 | INVERSION | subject-auxiliary inversion after fronted negative adverbial ("Not until...") |
| 13 | NONFINITE_VERB_PHRASES | infinitive modifying ordinal/superlative noun ("the first...to") |
| 14 | WORD_ORDER_MODIFICATION | noun + postpositive adjective phrase word order |
| 15 | EXISTENTIAL_EXPLETIVE | expletive "there + be" construction vs. pronoun/determiner |

Test Bの15問では14カテゴリ中10カテゴリが出現した（`VERB_FORM_VOICE`, `PARALLEL_STRUCTURE`,
`REFERENCE_AND_DETERMINERS`, `NOUN_CLAUSES`は1問のみ、または未出現）。これは他テストの分析で
埋まっていく想定であり、現時点でカテゴリを削る理由にはならない。
