import * as echarts from "echarts/core";
import {
	LineChart,
	BarChart as EBarChart,
	ScatterChart,
	GaugeChart,
	FunnelChart,
	HeatmapChart,
} from "echarts/charts";
import {
	GridComponent,
	TooltipComponent,
	LegendComponent,
	DataZoomComponent,
	VisualMapComponent,
	MarkLineComponent,
	MarkAreaComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([
	LineChart,
	EBarChart,
	ScatterChart,
	GaugeChart,
	FunnelChart,
	HeatmapChart,
	GridComponent,
	TooltipComponent,
	LegendComponent,
	DataZoomComponent,
	VisualMapComponent,
	MarkLineComponent,
	MarkAreaComponent,
	CanvasRenderer,
]);

export { echarts };
export type { EChartsOption } from "echarts";
