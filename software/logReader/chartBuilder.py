import copy
import math
import json

from bokeh.plotting import figure, output_file, show, reset_output, ColumnDataSource
from bokeh.models import HoverTool, Range1d, LinearAxis, LinearColorMapper, ColorBar, BasicTicker, PrintfTickFormatter, CustomJS, TapTool, Slider, widgets
from bokeh.layouts import row, widgetbox
from bokeh import events

from . import intersect

def MQTBChart(dataList, labelList, chartTitle=None, mode=None, patchLoad=None):
	colorsSource = ['steelblue', 'teal', 'indigo', 'greenyellow', 'gray', 'fuchsia', 'yellow', 'black', 'purple', 'orange', 'green', 'blue','red']
	colors = copy.copy(colorsSource)
	xLabel = labelList['x']
	yLabel = labelList['y']
	yScale = labelList['yScale']
	
	figureArgs ={}
	figureArgs['y_range']=[0, yScale]



	outputFile = './output/'+mode+'.html'
	outputTitle = mode
	if chartTitle:
		outputTitle = chartTitle

	output_file( outputFile, title=outputTitle, mode='cdn' )

	tooltipList = [
			#("index", "$index"),
			(xLabel, "@x{1.}"),
			(yLabel, "@y{1.11}"),
		]

	extraDataTooltips = set()
	for item in dataList[::-1]:
		for key in item['data'].keys():
			if key == 'z': continue
			if key == 'x': continue
			if key == 'y': continue
			print 'extra key', key
			extraDataTooltips.add( (key.replace('_', ' '), '@'+key+'{1.11}') )

	print 'extra', extraDataTooltips

	tooltipList.extend(extraDataTooltips)

	hover = HoverTool(
		tooltips = tooltipList,
		names=['propLine', 'scatterPlot']
		#mode='vline',
	)

	# load up the patch data, building the polygons for each efficiency range
	patches = {}
	patches['data'] = {}
	outsidePoints = []
	if patchLoad:
		patches, outsidePoints = loadPatchDump(patchLoad)

		#if loading a patch file over ride the display range of the chart to fit
		figureArgs['y_range']=[0, patches['ymax']*1.1]
		figureArgs['x_range']=[0, patches['xmax']*1.15]


	p = figure(
		width=890, plot_height=490,
		tools=[hover,'crosshair'],#"resize,pan,wheel_zoom,box_zoom,reset,box_select,lasso_select,hover",
		active_scroll=None,

		x_axis_label=xLabel, y_axis_label=yLabel,
		output_backend="webgl",
		title=outputTitle,
		**figureArgs
	)
	



	mapperColors = ["#d7191c", "#CF353D", "#C7505E", "#CF7E8C", "#CDA0B1", "#cac2d6", "#9EB5DA", "#72A8DE", "#459AE2", "#198de6"]
	mapper = LinearColorMapper(palette=mapperColors, low=.0, high=1)
	mapperLegend = LinearColorMapper(palette=mapperColors, low=.0, high=100)

	allScatter = []

	if (outputTitle == 'Torque Over RPM') or (patchLoad):
		color_bar = ColorBar(color_mapper=mapperLegend, major_label_text_font_size="8pt",
                     ticker=BasicTicker(desired_num_ticks=len(colors)),
                     formatter=PrintfTickFormatter(format="%d%%"),
                     label_standoff=6, border_line_color=None, 
                     height=200, location=(-80, 180))
		p.add_layout(color_bar, 'right')

		if patches:
			addPatchToChart(patches, outsidePoints, mapperColors, p)

	findIntersections(dataList, outsidePoints, p)


	# load the actual plots
	for item in dataList[::-1]:
		if not colors:
			colors = copy.copy(colorsSource)

		print 'creating plot for', item['label'], item['mode']

		data = item['data']

		source = ColumnDataSource( data=data)

		if item['mode']=='line':
			p.line('x', 'y', source=source, name='propLine', legend=item['label'], color=colors.pop(), line_width=3)

		else:
			scatterSize = 8
			thisColor = colors.pop()
			thisScatter = p.scatter('x', 'y', source=source, name='scatterPlot', legend=item['label'], color=thisColor, size=scatterSize)
			allScatter.append(thisScatter)

	p.legend.location = "top_left"
	p.legend.click_policy="hide"



	layout = row(
		p,
	)


	show(layout)
	reset_output()


def freelookChart(dataList, labelList, chartTitle=None, mode=None, patchLoad=None):
	colorsSource = ['steelblue', 'teal', 'indigo', 'greenyellow', 'gray', 'fuchsia', 'yellow', 'black', 'purple', 'orange', 'green', 'blue','red']
	colors = copy.copy(colorsSource)
	xLabel = labelList['x']
	yLabel = labelList['y']
	yScale = labelList['yScale']
	
	figureArgs ={}
	figureArgs['y_range']=[0, yScale]



	outputFile = './output/'+mode+'.html'
	outputTitle = mode
	if chartTitle:
		outputTitle = chartTitle

	output_file( outputFile, title=outputTitle, mode='cdn' )

	tooltipList = [
			#("index", "$index"),
			(xLabel, "@x{1.}"),
			(yLabel, "@y{1.11}"),
		]

	extraDataTooltips = set()
	for item in dataList[::-1]:
		for key in item['data'].keys():
			if key == 'z': continue
			if key == 'x': continue
			if key == 'y': continue
			print 'extra key', key
			extraDataTooltips.add( (key.replace('_', ' '), '@'+key+'{1.11}') )

	print 'extra', extraDataTooltips

	tooltipList.extend(extraDataTooltips)

	hover = HoverTool(
		tooltips = tooltipList,
		names=['propLine', 'scatterPlot']
		#mode='vline',
	)

	# load up the patch data, building the polygons for each efficiency range
	patches = {}
	patches['data'] = {}
	outsidePoints = []
	if patchLoad:
		patches, outsidePoints = loadPatchDump(patchLoad)

		#if loading a patch file over ride the display range of the chart to fit
		figureArgs['y_range']=[0, patches['ymax']*1.1]
		figureArgs['x_range']=[0, patches['xmax']*1.15]


	p = figure(
		width=1520, plot_height=880,
		tools=[hover,'pan','box_zoom','wheel_zoom', 'reset','crosshair'],
		active_scroll='wheel_zoom',

		x_axis_label=xLabel, y_axis_label=yLabel,
		output_backend="webgl",
		title=outputTitle,
		**figureArgs
	)
	



	mapperColors = ["#d7191c", "#CF353D", "#C7505E", "#CF7E8C", "#CDA0B1", "#cac2d6", "#9EB5DA", "#72A8DE", "#459AE2", "#198de6"]
	mapper = LinearColorMapper(palette=mapperColors, low=.0, high=1)
	mapperLegend = LinearColorMapper(palette=mapperColors, low=.0, high=100)

	allScatter = []



	if (outputTitle == 'Torque Over RPM') or (patchLoad):
		color_bar = ColorBar(color_mapper=mapperLegend, major_label_text_font_size="8pt",
                     ticker=BasicTicker(desired_num_ticks=len(colors)),
                     formatter=PrintfTickFormatter(format="%d%%"),
                     label_standoff=6, border_line_color=None, 
                     height=200, location=(-80, 180))
		p.add_layout(color_bar, 'right')

		if patches:
			addPatchToChart(patches, outsidePoints, mapperColors, p)


	findIntersections(dataList, outsidePoints, p)

	for item in dataList[::-1]:
		if not colors:
			colors = copy.copy(colorsSource)

		print 'creating plot for', item['label'], item['mode']

		data = item['data']

		source = ColumnDataSource( data=data)

		if item['mode']=='line':
			p.line('x', 'y', source=source, name='propLine', legend=item['label'], color=colors.pop(), line_width=3)

		else:
			scatterSize = 8
			thisColor = colors.pop()
			thisScatter = p.scatter('x', 'y', source=source, name='scatterPlot', legend=item['label'], color=thisColor, size=scatterSize)
			allScatter.append(thisScatter)

	p.legend.location = "top_left"
	p.legend.click_policy="hide"


	layout = row(
		p,
	)


	show(layout)
	reset_output()



def findIntersections(dataList, outsidePoints, plot):
	intersectRenderers = []
	intersectData = {'rpm':[], 'torque':[], 'thrust':[], 'prop':[]}

	for item in dataList[::-1]:
		found = False
		data = item['data']
		if 'thrust_g' not in data.keys():
			continue
		for outPointIndex in xrange(1, len(outsidePoints)):
			outLineA = outsidePoints[outPointIndex-1]
			outLineB = outsidePoints[outPointIndex]
			for linePointIndex in xrange(1, len(data['x'])):
				lineA = [ data['x'][linePointIndex-1], data['y'][linePointIndex-1] ]
				lineB = [ data['x'][linePointIndex], data['y'][linePointIndex] ]

				intersection = intersect.intersect( outLineA,outLineB, lineA,lineB )
				if intersection is not None:
					print 'found intersect', intersection
					interpDist =  intersect.dist(lineA, lineB, intersection )
					print 'interp',interpDist
					T1 = data['thrust_g'][linePointIndex-1]
					T2 = data['thrust_g'][linePointIndex]
					Tinterp = T1+ (T2-T1)*interpDist

					intersectData['rpm'].append(intersection[0])
					intersectData['torque'].append(intersection[1])
					intersectData['thrust'].append(Tinterp)
					intersectData['prop'].append(item['label'])


					found = True
					break
			if found: break

	intersectSource = ColumnDataSource(data=intersectData)
	intersectRenderers.append( plot.circle( 'rpm', 'torque', source=intersectSource, name='intersect', fill_color="white", size=12) )

	plot.add_tools(HoverTool( 
				names=['intersect'],
		tooltips = [
		('prop', '@prop', ),
		('RPM', "@rpm{1.}"),
		('Torque Ncm', "@torque{1.11}"),
		('Thrust g', "@thrust{1.1}"),
	]))

	return intersectRenderers


def loadPatchDump(patchLoad):

	patches = {}
	patches['data'] = {}
	outsidePoints = []
	patches['ymax']=0
	patches['xmax']=0

	for shapeRange in xrange(9,0,-1):
		patches['data'][shapeRange] = {}
		patches['data'][shapeRange]['x']=[]
		patches['data'][shapeRange]['y']=[]
		if not patchLoad[shapeRange]: continue

		#load up the front side of the polygon
		for index in xrange(0, len(patchLoad[shapeRange])):
			patches['data'][shapeRange]['x'].append( patchLoad[shapeRange][index][0] )
			patches['data'][shapeRange]['y'].append( patchLoad[shapeRange][index][1] )
			patches['xmax'] = max(patches['xmax'], patchLoad[shapeRange][index][0])
			patches['ymax'] = max(patches['ymax'], patchLoad[shapeRange][index][1])

		#close the back side of the polygon with the previous range points
		tempRange = patchLoad[shapeRange+1]
		#if the front side curve intersects with the backside curve trim the backside curve range to keep just the intersection region
		if patchLoad[shapeRange][0] in tempRange:
			tempRange = tempRange[ tempRange.index(patchLoad[shapeRange][0]): ]
		else:
			outsidePoints.append( patchLoad[shapeRange][0] )
		if patchLoad[shapeRange][-1] in tempRange:
			tempRange = tempRange[ : tempRange.index(patchLoad[shapeRange][-1])]
		else:
			outsidePoints.append( patchLoad[shapeRange][-1] )

		for index in xrange(len(tempRange)-1, -1, -1): #backside points load backwards
			patches['data'][shapeRange]['x'].append( tempRange[index][0] )
			patches['data'][shapeRange]['y'].append( tempRange[index][1] )

	#sort the outside points by X
	outsidePoints.sort(key=lambda x: x[1]  )

	return patches, outsidePoints



def addPatchToChart(patches, outsidePoints, mapperColors, plot):
	for index in patches['data']:
		if index>len(mapperColors)-1:
			thisColor = mapperColors[-1]
		else:
			thisColor = mapperColors[index]
		plot.patch( patches['data'][index]['x'], patches['data'][index]['y'], name='dynoPatch', alpha=0.5, line_width=2, fill_color=thisColor)

	outsideX = []
	outsideY = []
	for item in outsidePoints:
		outsideX.append(item [0])
		outsideY.append(item [1])
	plot.line( outsideX, outsideY, name='testEdge', color='black', line_width=4, )
