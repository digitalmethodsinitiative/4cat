# Munin plugins for 4CAT

Munin is software that can be used to monitor a server. It reports load 
averages, disk usage, database queries, et cetera, over time, via a web
interface that show you pretty charts and can be used to check if 
everything is running correctly.

The Python 3 scripts in this folder can be used as Munin plugins to
generate over-time statistics for a number of 4CAT-related metrics. To
add them, create a symlink to the scripts in (usually) 
`/etc/munin/plugins`. The plugin can then be enabled with 
`munin-run [plugin-name]`. You may want to leave the `.py` extension out in
the symlink, or it will show up in the web interface, et cetera.