"""全域 HTTP 設定:帶 cookie 跟隨跳轉。
證交所等網站的防火牆會對雲端主機先回 307 + Set-Cookie,要帶著 cookie 再連一次才會給資料;
urllib 預設不存 cookie,會一直被轉址而失敗。import 這個模組即生效。"""
import urllib.request, http.cookiejar
JAR = http.cookiejar.CookieJar()
_op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(JAR))
_op.addheaders = [("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"),
                  ("Accept-Language", "zh-TW,zh;q=0.9")]
urllib.request.install_opener(_op)
