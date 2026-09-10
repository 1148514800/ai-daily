import type { GitHubRepo } from '../types';

export const githubRepos: GitHubRepo[] = [
  {
    id: 'gh-llama-cpp',
    name: 'ggml-org/llama.cpp',
    description: 'LLM inference in C/C++',
    stars: 87240,
    starsDelta: 312,
    language: 'C++',
    summaryZh: '在本地和手机上运行大模型的事实标准之一，最近的更新更关注移动端调度和内存稳定性。',
    whyWatch: '如果你关心端侧摘要、离线阅读或把模型塞进 Android，这个仓库仍然是最先看的地方。',
    url: 'https://github.com/ggml-org/llama.cpp',
  },
  {
    id: 'gh-vllm',
    name: 'vllm-project/vllm',
    description: 'A high-throughput and memory-efficient inference engine for LLMs',
    stars: 58410,
    starsDelta: 428,
    language: 'Python',
    summaryZh: '服务端推理的主流引擎。前缀缓存和批量解码的改进，对每天固定模板的新闻摘要很有用。',
    whyWatch: '做日报后端时，它决定的是吞吐和成本，而不是模型本身聪不聪明。',
    url: 'https://github.com/vllm-project/vllm',
  },
  {
    id: 'gh-transformers',
    name: 'huggingface/transformers',
    description: 'Transformers: State-of-the-art Machine Learning for Pytorch, TensorFlow, and JAX.',
    stars: 152300,
    starsDelta: 190,
    language: 'Python',
    summaryZh: '模型加载、分词器和常见训练接口仍然从这里开始。新模型发布后，通常会先出现在这个生态里。',
    whyWatch: '它是看“今天又多了哪些可下载模型”的最快窗口之一。',
    url: 'https://github.com/huggingface/transformers',
  },
  {
    id: 'gh-sglang',
    name: 'sgl-project/sglang',
    description: 'SGLang is a fast serving framework for large language models and vision language models.',
    stars: 19680,
    starsDelta: 540,
    language: 'Python',
    summaryZh: '面向结构化输出和多模态服务的推理框架，最近在工具调用和缓存命中率上讨论很多。',
    whyWatch: '适合关注高速推理、JSON 输出和视觉语言模型服务的人。',
    url: 'https://github.com/sgl-project/sglang',
  },
  {
    id: 'gh-open-webui',
    name: 'open-webui/open-webui',
    description: 'User-friendly AI Interface',
    stars: 114900,
    starsDelta: 276,
    language: 'Svelte',
    summaryZh: '本地模型的常用前端。界面越来越像日常阅读和工作台，而不只是聊天调试器。',
    whyWatch: '想快速体验本地模型，又不想自己做 UI 时，它仍然是最省事的选择。',
    url: 'https://github.com/open-webui/open-webui',
  },
  {
    id: 'gh-markitdown',
    name: 'microsoft/markitdown',
    description: 'Python tool for converting files and office documents to Markdown.',
    stars: 81200,
    starsDelta: 165,
    language: 'Python',
    summaryZh: '把 PDF、网页和办公文档转成 Markdown，方便后续做摘要、切片和向量化。',
    whyWatch: '新闻和论文进入日报流水线前，通常需要先变成干净的文本。',
    url: 'https://github.com/microsoft/markitdown',
  },
  {
    id: 'gh-rerankers',
    name: 'AnswerDotAI/rerankers',
    description: 'A lightweight unified API for various reranking models',
    stars: 2180,
    starsDelta: 94,
    language: 'Python',
    summaryZh: '用统一接口接不同 rerank 模型，适合给小型新闻库做第二轮排序。',
    whyWatch: '历史日报和收藏检索不一定需要大模型，先把重排做对就很有感。',
    url: 'https://github.com/AnswerDotAI/rerankers',
  },
  {
    id: 'gh-mlx-lm',
    name: 'ml-explore/mlx-lm',
    description: 'Run LLMs with MLX',
    stars: 2430,
    starsDelta: 88,
    language: 'Python',
    summaryZh: '在 Apple Silicon 上跑本地 LLM 的轻量工具集，长文本和批处理最近更稳了。',
    whyWatch: '如果你在 Mac 上做本地摘要实验，它比搭一套完整服务更轻。',
    url: 'https://github.com/ml-explore/mlx-lm',
  },
];

export function getRepoById(id: string): GitHubRepo | undefined {
  return githubRepos.find((item) => item.id === id);
}

export function getReposByIds(ids: string[]): GitHubRepo[] {
  return ids
    .map((id) => getRepoById(id))
    .filter((item): item is GitHubRepo => item !== undefined);
}
