(()=>{
  document.querySelectorAll('.tw-fundamental-widget').forEach((host)=>{
    if(host.dataset.loaded) return;
    host.dataset.loaded='1';
    const box=document.createElement('div');
    box.className='tradingview-widget-container';
    box.style.width='100%';
    box.style.height='100%';
    const inner=document.createElement('div');
    inner.className='tradingview-widget-container__widget';
    inner.style.width='100%';
    inner.style.height='100%';
    box.appendChild(inner);
    const script=document.createElement('script');
    script.src='https://s3.tradingview.com/external-embedding/embed-widget-events.js';
    script.async=true;
    script.textContent=JSON.stringify({
      colorTheme:'dark',
      isTransparent:false,
      width:'100%',
      height:'100%',
      locale:'en',
      importanceFilter:'1',
      currencyFilter:'USD'
    });
    box.appendChild(script);
    host.appendChild(box);
  });
})();
