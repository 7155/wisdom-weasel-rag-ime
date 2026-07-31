(() => {
  const details = () => [...document.querySelectorAll('details')];
  document.getElementById('expand')?.addEventListener('click', () => {
    details().forEach((item) => { item.open = true; });
  });
  document.getElementById('collapse')?.addEventListener('click', () => {
    details().forEach((item) => { item.open = false; });
  });
  document.getElementById('search')?.addEventListener('input', (event) => {
    const query = event.target.value.trim().toLowerCase();
    document.querySelectorAll('.model-call').forEach((item) => {
      item.hidden = Boolean(query) && !item.dataset.search.includes(query);
    });
  });
})();
