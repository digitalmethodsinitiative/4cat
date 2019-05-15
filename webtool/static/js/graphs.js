var graphs = {
    init: function () {
        if($('body').hasClass('style-corporate')) {
            Highcharts.setOptions({
               colors: [
                   "#c52731",
                   "#98dd5c",
                   "#39208d",
                   "#05f1ac",
                   "#b31585",
                   "#2a8504",
                   "#8256cb",
                   "#8f8e00",
                   "#004a92",
                   "#da8217",
                   "#c2a6ff",
                   "#004700",
                   "#ff7ba9",
                   "#f9ce85",
                   "#ff7d5b"
               ]
            });
        } else {
            Highcharts.setOptions({
                colors: [
                    '#FF0000',
                    '#00FF00',
                    '#FFFF00',
                    '#0000FF',
                    '#FF00FF',
                    '#00FFFF',
                    '#000000',
                    '#800000',
                    '#008000',
                    '#000080',
                    '#800080',
                    '#008080',
                    '#808000',
                    '#A6CAF0',
                    '#A0A0A4',
                    '#808080',
                    '#C0C0C0',
                    '#C0DCC0',
                ]
            });
        }

        let months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

        $('body').on('change', '.graph-nav', function () {
            let graph_id = $(this).attr('name').replace('board', 'graph');
            console.log(graph_id);

            let series = {};
            console.log($(this).find('option:selected'));
            let times = JSON.parse($(this).find('option:selected').attr('data-times'));
            let all_data = JSON.parse($(this).find('option:selected').attr('data-values'));

            let min_val = 9999999999999999999;
            let max_val = 0;

            times = times.map(function (timestamp) {
                let date = new Date((timestamp + 3600) * 1000);
                return (date.getDate() + 1) + ' ' + months[date.getMonth()];
            });

            for (let time in all_data) {
                for (let item in all_data[time]) {
                    if (!series.hasOwnProperty(item)) {
                        let label = all_data[time][item][0];
                        if (label == '') {
                            label = '(none)';
                        }
                        series[item] = {data: [], name: label};
                    }
                    let value = parseInt(all_data[time][item][1]);
                    series[item].data.push(value);
                    min_val = Math.min(min_val, value);
                    max_val = Math.max(max_val, value);
                }
            }

            array_series = [];
            for (let label in series) {
                array_series.push(series[label]);
            }

            graph_container = $('#' + graph_id);

            if (graph_container.hasClass('stacked-bar')) {
                Highcharts.chart(graph_id, {
                    chart: {type: 'column'},
                    title: {text: undefined},
                    xAxis: {categories: times},
                    yAxis: {min: 0, title: {text: 'Activity'}},
                    legend: {reversed: true},
                    plotOptions: {series: {stacking: 'normal'}},
                    series: array_series
                })
            } else {
                let height;
                if (graph_container.hasClass('alluvial')) {
                    height = '75%';
                } else {
                    height = '50%';
                }

                Highcharts.chart(graph_id, {
                    plotOptions: {series: {lineWidth: 10}},
                    chart: {type: 'spline', height: height},
                    title: {text: undefined},
                    xAxis: {categories: times},
                    yAxis: {min: min_val, max: max_val, title: {text: 'Usage'}},
                    series: array_series
                })
            }
        });

        $('.graph-nav').each(function () {
            $(this).find('option:eq(0)').prop('selected', true);
            $(this).trigger('change');
        });
    }
};

$(document).ready(graphs.init);