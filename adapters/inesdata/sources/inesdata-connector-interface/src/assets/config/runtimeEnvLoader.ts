export const runtimeEnvLoader = new Promise<any>((resolve) => {
  const xmlhttp = new XMLHttpRequest(),
    method = 'GET',
    url = './assets/config/app.config.json';
    xmlhttp.open(method, url, true);
    xmlhttp.onload = function() {
      if (xmlhttp.status === 200) {
        resolve(JSON.parse(xmlhttp.responseText));
      } else {
        resolve(JSON.parse("{ \"runtime\": \"\" }"));
      }
    };
  xmlhttp.send();
});
