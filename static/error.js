// 全局 fetch 拦截器：处理 401/403/500 网络错 + 会话过期引导。v2.1.0 引入。
(function () {
  const ORIG = window.fetch.bind(window);
  window.fetch = async function (input, init) {
    try {
      const r = await ORIG(input, init);
      if (r.status === 401 || r.status === 403) {
        // 登录页/分享页不要拦截，让它们自己处理
        const onAuthPage = location.pathname === '/' || location.pathname.startsWith('/s/');
        if (!onAuthPage && r.status === 401) {
          if (window.toast) {
            window.toast.error('会话已过期，正在跳转登录…', 3000);
          }
          setTimeout(() => { location.href = '/'; }, 1200);
        }
      } else if (r.status >= 500) {
        if (window.toast) window.toast.error('服务暂时不可用（' + r.status + '）');
      }
      return r;
    } catch (e) {
      if (window.toast) window.toast.error('网络错误，请检查连接');
      throw e;
    }
  };
})();
