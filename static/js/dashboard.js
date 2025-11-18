// static/js/dashboard.js

(function(){
	const pieEl = document.getElementById('pie');
	if(!pieEl) return;
	const ctx = pieEl.getContext('2d');
	new Chart(ctx, {
		type: 'pie',
		data: {
			labels: ['Present','Absent'],
			datasets: [{ data: [present||0, absent||0], backgroundColor:['#16a34a','#ef4444'] }]
		},
		options: { responsive:false, plugins:{ legend:{ position:'bottom' } } }
	});
})();
