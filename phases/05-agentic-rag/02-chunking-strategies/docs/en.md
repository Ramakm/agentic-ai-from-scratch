# Chunking Strategies

> Where you cut a document decides which facts can ever be found whole. Cut on meaning, not on character counts, and tell every chunk where it came from.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 5 · Lesson 1
**Time:** ~45 minutes

## Learning Objectives

- Implement five chunkers: fixed-size, fixed-size with overlap, sentence packing, Markdown sections, and sections prefixed with their heading path.
- Measure a chunker with two numbers: how many facts survive intact in some chunk, and how many questions retrieve a chunk containing the whole fact.
- Explain why overlap keeps facts intact but can hurt retrieval, and why heading paths help short sections get found.
- Choose a chunk size and strategy for a corpus from measurements, not defaults.

## The Problem

In Lesson 1, the answer to "who is the deputy?" came back as "Luis Fe". The retriever found the right chunk. The chunker had cut the name in half.

Chunking looks like plumbing: split documents so they fit the embedding model, pick 500 tokens because the tutorial did, move on. But every later step works on chunks. A fact split across two chunks can only be retrieved in halves. A chunk that says "the nightly limit is 150 euros" with no mention of hotels may never match a question about hotels. A chunk that mixes three topics matches all of them weakly.

## The Concept

### Five chunkers

| Chunker | Cuts at | Keeps together | Weakness |
|---------|---------|----------------|----------|
| **Fixed** | Every N characters | Nothing in particular | Cuts words, sentences, names |
| **Fixed + overlap** | Every N − overlap characters, chunks overlap | A fact near a boundary appears whole in one of two chunks | More chunks; each still mixes topics; duplicate hits |
| **Sentences** | Sentence ends, packed up to N | Whole sentences | Can still mix sections |
| **Sections** | Markdown headings (then sentences if long) | A section's topic | Short sections lose the context their heading gave them |
| **Sections + path** | Headings, and each chunk starts with `Travel > Hotels > Capital cities:` | Topic and where it sits | Slightly longer chunks |

### Two measurements

| Measure | Question it answers |
|---------|---------------------|
| **Facts intact** | Is each needed fact fully inside at least one chunk? If not, no retriever can find it whole. |
| **Top-1 has fact** | Does the best-ranked chunk for each question contain the whole fact? |

The first measures the chunker alone. The second measures the chunker together with retrieval. A chunker can keep every fact intact and still lose on the second, if its chunks are noisy or missing context.

### Context in the chunk

A section under "### Hotels / #### Most cities" may say only "The nightly limit is 150 euros, including breakfast." The words *hotel* and *city* are in the headings, not the text. Prefixing the heading path puts them back. Anthropic's Contextual Retrieval goes further and has a model write a short context sentence for every chunk; the heading path is the free version of the same idea.

## Build It

```bash
cd code
python3 main.py
```

```text
chunker         chunks avg chars  facts intact  top-1 has fact
fixed                8       111           5/7             3/7
fixed+overlap       11       117           7/7             4/7
sentences            9        97           7/7             6/7
sections             7        98           7/7             6/7
sections+path        7       124           7/7             7/7

the Paris chunk, as each chunker cuts it:
  fixed           '.\n#### Capital cities\nIn London, Paris and Zurich the nightly limit is 220 euros. Book through the travel portal so the '
  fixed+overlap   '\n### Hotels\n#### Most cities\nThe nightly limit is 150 euros, including breakfast.\n#### Capital cities\nIn London, Paris a'
  sentences       'In London, Paris and Zurich the nightly limit is 220 euros. Book through the travel portal so the rate is applied.'
  sections        'In London, Paris and Zurich the nightly limit is 220 euros. Book through the travel portal so the rate is applied.'
  sections+path   'Travel > Hotels > Capital cities: In London, Paris and Zurich the nightly limit is 220 euros. Book through the travel portal so the rate is applied.'
```

Seven questions over one Markdown handbook, 120-character chunks, offline hashed embeddings:

- **Fixed** cut two facts in half (5/7 intact) and found the whole fact for only 3 questions.
- **Fixed + overlap** keeps every fact intact somewhere, but the extra half-chunks compete with the good ones: 4/7. Overlap helps the first number more than the second.
- **Sentences** and **sections** keep everything intact and find 6/7. Their misses differ.
- **Sections + path** finds all 7. The question it alone gets right is "What is the nightly hotel limit in most cities?": the section text never says "hotel" or "cities", and only the path does.

The bottom half prints the first chunk mentioning Paris under each chunker. Read them as the model would.

### Step 1: `fixed()`

`text[i:i+size]` with a step of `size - overlap`. With no overlap, joining the chunks gives back the document exactly (a test checks), so nothing is lost, only cut.

### Step 2: `sentences()`

Splits on sentence ends and line breaks, then packs pieces into chunks up to `size`. A single sentence longer than `size` stays whole rather than being cut. Use a real sentence splitter for production text with abbreviations ("e.g.", "Dr.").

### Step 3: `sections()`

Walks the Markdown line by line, keeps the current heading path (`path[:level-1] + [heading]`), and flushes the body when a new heading starts. Long sections are packed with `sentences()`. With `with_path=True`, each chunk starts with the headings below the document title.

### Step 4: Measure, then choose

`evaluate()` reports chunk count, average size, facts intact and top-1 hits for any chunker. Try changing `size` in `fixed()` and `sentences()`: at 160 characters every chunker keeps every fact intact on this small handbook, and the differences mostly vanish. Chunk size interacts with how long your facts are; measure on your own documents.

### Step 5: With a real embedding model

```bash
export AGENT_BASE_URL=http://localhost:11434/v1
export AGENT_EMBED_MODEL=nomic-embed-text
python3 main.py --live
```

"Facts intact" doesn't depend on the embedder; "top-1" does. Does a neural embedder close the gap between sections and sections + path, or does the heading path still help?

### Run the tests

```bash
python3 -m unittest -v test_main
```

Eight tests: lossless fixed chunks, overlap, sentences never cut, long sentences kept whole, sections and paths, path reset at a higher heading, the scoreboard, and the question only the path rescues.

## Use It

| Tool | Chunkers |
|------|----------|
| LangChain | `RecursiveCharacterTextSplitter`, `MarkdownHeaderTextSplitter` (keeps headers as metadata) |
| LlamaIndex | `SentenceSplitter`, `MarkdownNodeParser`, `SemanticSplitterNodeParser` |
| Unstructured, Docling | Parse PDFs and Office files into elements (titles, tables, lists) before chunking |
| Anthropic Contextual Retrieval | A model writes a context sentence for each chunk before embedding |

Parse structure first, chunk second. A PDF flattened to plain text has already lost the headings this lesson relies on.

## Ship It

`outputs/skill-chunking-choice.md` is a skill that picks a chunking strategy for a corpus: parse structure, try several chunkers and sizes, measure facts intact and top-k hits on real questions, and add heading paths or context to chunks.

## Exercises

1. **Easy.** Set the overlap to 0, 20, 40 and 60. Plot facts intact and top-1 hits. Where do they peak?
2. **Medium.** Store the heading path as metadata instead of text, and prepend it only when embedding (not when showing the chunk to the model). Does retrieval change? Does the prompt get shorter?
3. **Medium.** Add a "parent document" strategy: retrieve small sentence chunks, but put the whole section into the prompt. Which failure from Lesson 1 does this address?
4. **Hard.** Add a table to the handbook (Markdown pipe table of hotel limits by city). Which chunkers break it? Write a chunker that keeps each table row together with the header row.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Chunk | "A split" | The unit that is embedded, retrieved and pasted into the prompt |
| Overlap | "Sliding window" | Repeating the end of one chunk at the start of the next, so boundary facts appear whole once |
| Structure-aware chunking | "Smart splitting" | Cutting at the document's own boundaries: headings, paragraphs, sentences, table rows |
| Heading path | "Breadcrumbs" | The chain of headings above a section, added to its chunks for context |
| Facts intact | "Coverage" | Whether each fact you need is fully inside at least one chunk |

## Further Reading

- [Anthropic, Introducing Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval)
- [LangChain, Text splitters](https://python.langchain.com/docs/concepts/text_splitters/)
- [LlamaIndex, Node parsers](https://docs.llamaindex.ai/en/stable/module_guides/loading/node_parsers/modules/)
- [Chen et al., Dense X Retrieval: What Retrieval Granularity Should We Use? (2023)](https://arxiv.org/abs/2312.06648)
