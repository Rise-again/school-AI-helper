import MarkdownIt from "markdown-it";
import DOMPurify from "dompurify";

/**
 * 助手回答统一走这里渲染：html:false 关掉原始 HTML，DOMPurify 再消毒一次，
 * 外链统一新窗口打开。流式期间不要调用（逐 token 重排会卡），结束后再渲染一次即可。
 */
const md = new MarkdownIt({ html: false, linkify: true, breaks: true });

const defaultLinkOpen =
  md.renderer.rules.link_open ??
  ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options));

md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  tokens[idx].attrSet("target", "_blank");
  tokens[idx].attrSet("rel", "noopener noreferrer");
  return defaultLinkOpen(tokens, idx, options, env, self);
};

export function renderMd(text: string): string {
  return DOMPurify.sanitize(md.render(text || ""));
}
