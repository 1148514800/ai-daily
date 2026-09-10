import type { DailyDigest } from '../types';
import { getNewsByIds } from './news';

export const TODAY_DATE = '2026-09-10';

export const digests: DailyDigest[] = [
  {
    date: '2026-09-10',
    title: '今日 AI 日报',
    description: '今日精选 10 条 AI 动态',
    highlight: '评测可复现、端侧长上下文，以及更适合资讯流水线的开源工具。',
    newsIds: [
      'n-20260910-01',
      'n-20260910-02',
      'n-20260910-03',
      'n-20260910-04',
      'n-20260910-05',
      'n-20260910-06',
      'n-20260910-07',
      'n-20260910-08',
      'n-20260910-09',
      'n-20260910-10',
    ],
  },
  {
    date: '2026-09-09',
    title: '昨日 AI 日报',
    description: '精选 3 条值得回看的动态',
    highlight: '截图补丁、Agent 证据链，以及本地长文本处理。',
    newsIds: ['n-20260909-01', 'n-20260909-02', 'n-20260909-03'],
  },
  {
    date: '2026-09-08',
    title: '9月8日 AI 日报',
    description: '精选 2 条检索与排序进展',
    highlight: '引用要到页码，轻量 reranker 也能提升旧闻查找。',
    newsIds: ['n-20260908-01', 'n-20260908-02'],
  },
  {
    date: '2026-09-07',
    title: '9月7日 AI 日报',
    description: '精选 2 条基础设施动态',
    highlight: '论文 OCR 更稳，模型发布开始认真对待许可证。',
    newsIds: ['n-20260907-01', 'n-20260907-02'],
  },
];

export function getTodayDigest(): DailyDigest {
  return digests[0];
}

export function getDigestByDate(date: string): DailyDigest | undefined {
  return digests.find((item) => item.date === date);
}

export function getHistoryDigests(): DailyDigest[] {
  return digests.filter((item) => item.date !== TODAY_DATE);
}

export function getDigestNews(digest: DailyDigest) {
  return getNewsByIds(digest.newsIds);
}
