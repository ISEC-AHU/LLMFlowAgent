import { Radar } from '@ant-design/plots';
import { Button, Card, Col, Divider, List, Row, Tabs, Tag, Typography } from 'antd';
import { useMemo, useRef, type ReactNode } from 'react';

const { Text } = Typography;

interface Props {
  loading: boolean;
  report: any;
  selectedCount: number;
  onGenerate: () => void;
}

function DimensionList({ data }: { data: any }) {
  return (
    <List
      dataSource={data?.dimension_scores || []}
      renderItem={(item: any, index: number) => {
        const score = Number(item.score || 0);
        let color = 'default';
        if (score >= 4.5) color = 'success';
        else if (score >= 3.5) color = 'processing';
        else if (score >= 2.5) color = 'warning';
        else color = 'error';

        return (
          <List.Item key={index}>
            <div className="w-full">
              <div className="flex items-center justify-between mb-1">
                <Text strong>{item.dimension_name}</Text>
                <Tag color={color}>{score.toFixed(1)}</Tag>
              </div>
              {item.reasoning && (
                <Text type="secondary" style={{ fontSize: 13 }}>
                  {item.reasoning}
                </Text>
              )}
            </div>
          </List.Item>
        );
      }}
    />
  );
}

export default function ReportCard({
  loading,
  report,
  selectedCount,
  onGenerate,
}: Props) {
  const radarWrapRef = useRef<HTMLDivElement | null>(null);

  const genericReport = report?.generic_report;
  const tsReport = report?.task_specific_report;

  const hasGeneric =
    genericReport &&
    Array.isArray(genericReport.dimension_scores) &&
    genericReport.dimension_scores.length > 0;
  const hasTs =
    tsReport &&
    Array.isArray(tsReport.dimension_scores) &&
    tsReport.dimension_scores.length > 0;

  /* Merge both rubric dimension sets into a single radar-chart data source. */
  const radarData = useMemo(() => {
    const combined: { shortName: string; score: number }[] = [];
    [genericReport, tsReport].forEach((r) => {
      if (r?.dimension_scores && Array.isArray(r.dimension_scores)) {
        r.dimension_scores.forEach((item: any) => {
          combined.push({
            shortName: item.dimension_name,
            score: Number(item.score || 0),
          });
        });
      }
    });
    return combined;
  }, [genericReport, tsReport]);

  const downloadRadarJpg = () => {
    const canvas = radarWrapRef.current?.querySelector('canvas') as HTMLCanvasElement | null;
    if (!canvas) return;

    const scale = 4;
    const exportCanvas = document.createElement('canvas');
    exportCanvas.width = canvas.width * scale;
    exportCanvas.height = canvas.height * scale;

    const ctx = exportCanvas.getContext('2d');
    if (!ctx) return;

    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, exportCanvas.width, exportCanvas.height);
    ctx.scale(scale, scale);
    ctx.drawImage(canvas, 0, 0);

    exportCanvas.toBlob(
      (blob) => {
        if (!blob) return;
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'workflow-radar-chart.jpg';
        a.click();
        URL.revokeObjectURL(url);
      },
      'image/jpeg',
      0.98,
    );
  };

  const radarConfig = {
    data: radarData,
    xField: 'shortName',
    yField: 'score',

    height: 460,
    autoFit: true,

    theme: {
      styleSheet: {
        fontFamily: 'Times New Roman',
      },
    },

    meta: {
      score: { min: 0, max: 5 },
    },

    appendPadding: [40, 60, 40, 60],

    area: {
      style: {
        fillOpacity: 0.25,
      },
    },

    line: {
      style: {
        lineWidth: 2,
        stroke: '#1677ff',
      },
    },

    point: {
      size: 4,
      style: {
        stroke: '#1677ff',
        lineWidth: 1,
      },
    },

    axis: {
      x: {
        labelFontFamily: 'Times New Roman',
        labelFontWeight: 900,
        labelFill: '#000000',
        labelFontSize: 13,
        labelFormatter: (text: string) => {
          if (text === 'Transcript-Aware Reverb') return 'Transcript-Aware\nReverb';
          if (text === 'Operational Robustness') return 'Operational\nRobustness';
          if (text === 'Waveform Readability') return 'Waveform\nReadability';
          if (text === 'Functional Requirement Coverage')
            return 'Functional\nRequirement\nCoverage';

          const words = text.split(' ');
          const lines: string[] = [];
          for (let i = 0; i < words.length; i += 2) {
            lines.push(words.slice(i, i + 2).join(' '));
          }
          return lines.join('\n');
        },
      },

      y: {
        labelFontFamily: 'Times New Roman',
        labelFill: '#666666',
        labelFontSize: 12,
      },
    },

    legend: {
      color: false,
    },
  };

  /* Build the detail tabs. */
  const tabItems = [
    hasGeneric
      ? {
          key: 'generic',
          label: 'Generic Rubric',
          children: <DimensionList data={genericReport} />,
        }
      : null,
    hasTs
      ? {
          key: 'task_specific',
          label: 'Task-Specific Rubric',
          children: <DimensionList data={tsReport} />,
        }
      : null,
  ].filter(Boolean) as { key: string; label: string; children: ReactNode }[];

  const hasReport = hasGeneric || hasTs;

  return (
    <Card
      title="Stage 4: Evaluation Result Generation"
      className="rounded-2xl shadow-sm"
      extra={
        <Button type="primary" loading={loading} onClick={onGenerate}>
          Generate Evaluation Report
        </Button>
      }
    >
      <div className="flex items-center justify-between">
        <Text type="secondary">
          Generate the evaluation report from the selected rubric dimensions.
        </Text>
        <Text type="secondary">Total Selected: {selectedCount}</Text>
      </div>

      <Divider />

      {report && hasReport ? (
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={10}>
            <Card
              title="Multidimensional Evaluation Radar Chart"
              size="small"
              className="rounded-xl"
              extra={
                <Button size="small" onClick={downloadRadarJpg}>
                  Save HD JPG
                </Button>
              }
            >
              <div
                ref={radarWrapRef}
                style={{
                  height: 400,
                  maxWidth: 560,
                  margin: '0 auto',
                }}
              >
                <Radar {...radarConfig} />
              </div>
            </Card>
          </Col>

          <Col xs={24} lg={14}>
            <Card title="Dimension Score Details" size="small" className="rounded-xl">
              <Tabs
                defaultActiveKey={hasTs ? 'task_specific' : 'generic'}
                items={tabItems}
              />
            </Card>
          </Col>
        </Row>
      ) : (
        <div className="py-8 text-center text-gray-400">No report generated yet</div>
      )}
    </Card>
  );
}
