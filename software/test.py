import numpy as np
from numpy import pi

from bokeh.client import push_session
from bokeh.driving import cosine
from bokeh.plotting import figure, curdoc

test = [2,3,None, 0, None,5,None,7]
cleanTest = [value for value in test if value is not None]
print cleanTest, min(cleanTest), max(cleanTest), np.median(np.array( cleanTest )), np.mean(np.array( cleanTest ))

'''

x = np.linspace(0, 4*pi, 80)
y = np.sin(x)

p = figure()
r1 = p.line([0, 4*pi], [-1, 1], color="firebrick")
r2 = p.line(x, y, color="navy", line_width=4)

# open a session to keep our local document in sync with server
session = push_session(curdoc())

@cosine(w=0.03)
def update(step):
    # updating a single column of the the *same length* is OK
    r2.data_source.data["y"] = y * step
    r2.glyph.line_alpha = 1 - 0.8 * abs(step)

curdoc().add_periodic_callback(update, 50)

session.show(p) # open the document in a browser

session.loop_until_closed() # run forever

'''