// Cloudflare Worker: зеркало api.telegram.org для серверов, где Telegram заблокирован.
// Деплой: dash.cloudflare.com → Workers & Pages → Create → Hello World → Edit code → вставить → Deploy.
export default {
  async fetch(request) {
    const url = new URL(request.url);
    // пускаем только запросы к Bot API
    if (!url.pathname.startsWith("/bot")) {
      return new Response("ok", { status: 200 });
    }
    url.hostname = "api.telegram.org";
    url.port = "";
    url.protocol = "https:";
    return fetch(new Request(url.toString(), request));
  },
};
