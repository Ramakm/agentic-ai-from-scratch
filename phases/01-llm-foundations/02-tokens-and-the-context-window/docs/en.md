# Tokens and the Context Window

> Models don't read characters or words. They read tokens, and every limit and price you'll meet is counted in them.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 1 · Lesson 1
**Time:** ~50 minutes

## Learning Objectives

- Explain what a token is, and implement byte-level byte-pair encoding (BPE): training, encoding and decoding.
- Explain why real tokenizers split text into word-sized chunks before merging.
- Measure how many tokens different kinds of text cost (prose, code, JSON, numbers, other scripts, emoji) with a real tokenizer.
- Budget a context window: fixed costs, reserved output, and how much history still fits.

## The Problem

"The context window is 128K" sounds like plenty, until an agent's run fills it with tool results. Then you find out what a token is the hard way: the 4,000-character report is 1,000 tokens, the JSON is more than you'd guess, and the same question in Hindi costs three times what it costs in English.

Phase 0 · Lesson 3 showed a local server silently cutting a prompt to fit its window. To avoid that, you need to know what tokens are and how to count them.

## The Concept

### A token is a learned chunk of bytes

A tokenizer has a fixed vocabulary, typically 32K to 200K entries. Each entry is a byte sequence: a whole common word (" agent"), part of a rarer one ("un"), punctuation, or a single byte. Text is split into the longest pieces the vocabulary allows, and the model sees a list of integer ids.

### Byte-pair encoding

| Step | What happens |
|------|--------------|
| Start | Every byte (0–255) is a token, so any text can be encoded |
| Count | Find the most frequent pair of adjacent tokens in the training text |
| Merge | Make that pair a new token; replace it everywhere |
| Repeat | Until the vocabulary reaches its target size |
| Encode new text | Apply the learned merges, in the order they were learned |

Frequent sequences in the training data become single tokens. Rare ones stay as several pieces. Text in scripts the tokenizer saw little of falls back toward one token per byte, and many scripts use 2–4 bytes per character in UTF-8.

### Pre-tokenization

Without a rule, BPE merges across words, and with repetitive data it learns whole sentences as single tokens. (This lesson's first draft did exactly that.) Real tokenizers first split text with a regex into chunks: words with their leading space, runs of punctuation, digits in groups of up to three. Merges happen only inside a chunk.

### The window is shared

| Takes space | Notes |
|-------------|-------|
| System prompt | Every call |
| Tool definitions | Every call where tools are offered |
| History | Grows every step |
| Output | Reserved: input + output must fit together |

## Build It

```bash
cd code
python3 main.py
```

```text
trained 118 merges on 837 characters
first merges: [' t', ' a', 'he', ' the', 'oo', ' m', 'on', 'es', ' i', ' r']
later merges: [' grow', ' grows', ' of', ' A', 'or', ' arg', ' argu', ' argume', ' argument', ' arguments']
'the agent calls a tool' -> ['t', 'he', ' agent', ' call', 's', ' a', ' tool']
'unbelievable' -> ['un', 'b', 'e', 'l', 'i', 'e', 'v', 'a', 'b', 'l', 'e']
```

The tokenizer learned " the", " agent", " tool" and, merge by merge, " argument" → " arguments". "unbelievable" never appeared in training, so it falls apart into almost single letters.

### Step 1: `train`

`chunks()` splits the corpus with the pre-tokenization regex. Each distinct chunk is a tuple of bytes with a count. Each round counts adjacent pairs across all chunks (weighted by how often the chunk occurs), merges the most frequent pair into a new id, and stops early when the best pair occurs only once.

### Step 2: `encode` and `decode`

`encode` splits new text into chunks and, within each chunk, repeatedly applies the earliest-learned merge that matches. `decode` maps ids back to bytes and joins them. The round-trip test covers prose, Hindi, emoji, accents, tabs and the empty string: byte-level BPE can encode anything, because every byte is in the vocabulary.

### Step 3: Compare kinds of text, with a real tokenizer

```bash
python3 main.py --live
```

The live mode counts tokens with llama3.2's own tokenizer, through Ollama's raw mode (no chat template, so the count is the text plus one beginning-of-text token, which is measured and subtracted):

```text
kind           chars bytes  our BPE chars/tok  llama3.2  chars/tok
English prose     68    68       24      2.83        13      5.23
Python code       48    48       37      1.30        18      2.67
JSON              68    68       61      1.11        23      2.96
Numbers           36    36       36      1.00        21      1.71
Hindi             61   157      157      0.39        34      1.79
Emoji              5    19       19      0.26        14      0.36
```

What the real numbers say:

1. **English prose is cheapest**: about 5 characters per token. The "4 characters per token" rule of thumb is for English, and even there it's rough (Phase 0 · Lesson 3 measured 5.26 on a longer text).
2. **Code and JSON cost about twice as much per character.** Braces, quotes and indentation are tokens too. Tool calls and tool results are JSON, so agents pay this rate on much of their context.
3. **Numbers are expensive.** "1,234,567" is several tokens, split into digit groups. One reason models struggle with arithmetic (Lesson 10).
4. **Hindi costs about 3× English per character**, and the same meaning usually needs a similar number of characters. Non-English users of your agent fill the window faster and pay more.
5. **Five emoji cost 14 tokens.**

Our toy tokenizer, trained on 837 characters of English, does worse everywhere: a 150-entry vocabulary versus llama3.2's ~128,000. Both fall back to bytes for anything they didn't learn.

### Step 4: Budget the window

```text
window budget, 8,192 tokens: {'fixed': 2524, 'history_total': 10000, 'kept_messages': 14, 'dropped_messages': 11, 'free': 68}
```

`budget()` subtracts the fixed costs (system prompt, tool definitions, reserved output) and keeps history messages newest-first until the next one doesn't fit. With 600 + 900 + 1,024 tokens fixed, only 14 of 25 history messages fit. Phase 4 covers what to do with the other 11.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Eight tests: round-trips for any text, compression on trained text, the merge step, merges never crossing chunks, byte fallback for unseen scripts, the vocabulary floor, and the window budget.

## Use It

| Tool | What it's for |
|------|---------------|
| `tiktoken` | OpenAI's fast BPE tokenizers; count tokens before sending |
| Hugging Face `tokenizers` / `AutoTokenizer` | The exact tokenizer for open models like Llama, Qwen, Mistral |
| Anthropic `count_tokens` endpoint | Exact input token counts for Claude, including tools and images |
| Ollama raw mode / `prompt_eval_count` | Exact counts for local models, as in this lesson |

Count with the model's own tokenizer whenever you can. Estimates are fine for rough planning only.

## Ship It

`outputs/skill-token-budget-check.md` is a skill that estimates where an agent's context goes (system, tools, history, tool results, reserved output), measures it with the model's real tokenizer, and flags content that is unusually expensive per character.

## Exercises

1. **Easy.** Add a sample of your own language and measure it with `--live`. How many times English's cost is it?
2. **Medium.** Train on the corpus without pre-tokenization (call the old algorithm on the raw byte list). Print the 10 longest learned tokens. What went wrong?
3. **Medium.** Compare the same tool result as pretty-printed JSON, minified JSON, and a plain-text table. Which is cheapest in real tokens?
4. **Hard.** Train with a vocabulary of 1,000 on a larger English text (a public-domain book). Plot chars/token against vocabulary size.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Token | "A word" | A vocabulary entry: a learned byte sequence, often a word piece with its leading space |
| BPE | "The tokenizer" | Byte-pair encoding: build a vocabulary by repeatedly merging the most frequent adjacent pair |
| Pre-tokenization | "Splitting" | Cutting text into word-sized chunks before BPE, so merges stay within words |
| Context window | "Memory" | The maximum tokens of input plus output for one call |
| BOS token | "Start token" | A special token marking the beginning of the text; counted but invisible |

## Further Reading

- [Sennrich et al., *Neural Machine Translation of Rare Words with Subword Units* (2016)](https://arxiv.org/abs/1508.07909)
- [Andrej Karpathy, *Let's build the GPT Tokenizer* and minbpe](https://github.com/karpathy/minbpe)
- [OpenAI tiktoken](https://github.com/openai/tiktoken)
- [Petrov et al., *Language Model Tokenizers Introduce Unfairness Between Languages* (2023)](https://arxiv.org/abs/2305.15425)
