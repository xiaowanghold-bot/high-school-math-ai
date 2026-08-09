const baseUrl = process.env.WEB_BASE_URL ?? "http://localhost:3000";
const endpoint = new URL("/api/v1/exam-papers", baseUrl);

try {
  const response = await fetch(endpoint, { signal: AbortSignal.timeout(5000) });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  const payload = await response.json();
  if (!Array.isArray(payload.items)) {
    throw new Error("响应中缺少试卷列表 items");
  }
  console.log(`PASS ${endpoint}：读取到 ${payload.items.length} 份试卷`);
} catch (error) {
  console.error(`FAIL ${endpoint}：${error instanceof Error ? error.message : error}`);
  process.exitCode = 1;
}
