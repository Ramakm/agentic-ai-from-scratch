// The same four ideas in TypeScript. Runs directly on Node 23.6+ (type stripping):
//   node main.ts
// Only "erasable" TypeScript is used (types, no enums), so no build step is needed.

// 1. typed messages: a union type for roles, validated at the boundary
type Role = "system" | "user" | "assistant" | "tool";
const ROLES: readonly Role[] = ["system", "user", "assistant", "tool"];

interface Message {
  role: Role;
  content: string;
  tool_call_id?: string;
}

function isMessage(x: unknown): x is Message {
  if (typeof x !== "object" || x === null) return false;
  const m = x as Record<string, unknown>;
  return ROLES.includes(m.role as Role) && typeof m.content === "string" &&
    (m.role !== "tool" || typeof m.tool_call_id === "string");
}

// 2. JSON at the boundary: parse untrusted input, then narrow its type
function fromWire(raw: string): Message[] {
  const data: unknown = JSON.parse(raw);
  if (!Array.isArray(data) || !data.every(isMessage)) throw new Error("invalid messages");
  return data;
}

// 3. async concurrency: Promise.all + a timeout per call + a concurrency limit
const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

async function fakeLlm(prompt: string, latencyMs: number): Promise<string> {
  await sleep(latencyMs);
  return `answer to "${prompt}"`;
}

function withTimeout<T>(p: Promise<T>, ms: number): Promise<T> {
  return Promise.race([p, sleep(ms).then(() => { throw new Error(`timed out after ${ms}ms`); })]);
}

type Result = { prompt: string; ok: true; text: string } | { prompt: string; ok: false; error: string };

async function runConcurrent(jobs: [string, number][], limit = 3, timeoutMs = 1000): Promise<Result[]> {
  const results: Result[] = new Array(jobs.length);
  let next = 0;
  async function worker(): Promise<void> {          // N workers pull from a shared queue
    while (next < jobs.length) {
      const i = next++;
      const [prompt, latency] = jobs[i];
      try {
        results[i] = { prompt, ok: true, text: await withTimeout(fakeLlm(prompt, latency), timeoutMs) };
      } catch (e) {
        results[i] = { prompt, ok: false, error: (e as Error).message };
      }
    }
  }
  await Promise.all(Array.from({ length: limit }, worker));
  return results;
}

// 4. async generators for streaming
async function* streamTokens(text: string): AsyncGenerator<string> {
  for (const word of text.split(" ")) {
    await sleep(15);
    yield word + " ";
  }
}

async function main(): Promise<void> {
  const wire = JSON.stringify([{ role: "user", content: "hi" }, { role: "tool", content: "{}", tool_call_id: "c1" }]);
  console.log("1-2. parsed", fromWire(wire).length, "messages");
  try { fromWire('[{"role":"robot","content":"x"}]'); } catch (e) { console.log("    rejected:", (e as Error).message); }

  const jobs: [string, number][] = [["summarize the doc", 300], ["extract the dates", 250],
    ["draft a reply", 300], ["classify the intent", 200], ["hang forever", 5000]];
  const t0 = performance.now();
  const results = await runConcurrent(jobs);
  console.log(`\n3. concurrent: ${((performance.now() - t0) / 1000).toFixed(2)}s`);
  for (const r of results) console.log(`    ${r.ok ? "ok " : "ERR"} ${r.prompt.padEnd(20)} ${r.ok ? r.text : r.error}`);

  let out = "";
  for await (const tok of streamTokens("Tokens arrive one at a time.")) out += tok;
  console.log("\n4. streamed:", out.trim());
}

main();
