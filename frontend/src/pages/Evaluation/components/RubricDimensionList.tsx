import { Checkbox, Col, Row } from 'antd';

interface Props {
  dimensions: any[];
  type: 'universal' | 'final';
  selectedItems: any[];
  onToggle: (type: 'universal' | 'final', item: any, checked: boolean) => void;
}

export default function RubricDimensionList({
  dimensions,
  type,
  selectedItems,
  onToggle,
}: Props) {
  if (!Array.isArray(dimensions) || dimensions.length === 0) {
    return <div className="py-8 text-center text-gray-400">No dimensions available</div>;
  }

  return (
    <Row gutter={[16, 16]}>
      {dimensions.map((item, index) => {
        const checked = selectedItems.some((x) => x.theme === item.theme);

        return (
          <Col xs={24} md={12} key={item.theme || index}>
            <div className="h-full rounded-xl border border-[#e5e6eb] bg-white p-4 shadow-sm transition hover:shadow-md">
              <div className="mb-3 flex items-start gap-3">
                <Checkbox
                  checked={checked}
                  onChange={(e) => onToggle(type, item, e.target.checked)}
                  className="mt-1"
                />
                <div className="mt-1 h-10 w-1 rounded-full bg-[#1677ff]" />
                <div className="flex-1">
                  <div className="text-[16px] font-semibold text-[#1f1f1f] leading-6">
                    {item.theme}
                  </div>
                </div>
              </div>

              <div className="pl-10 text-[14px] leading-6 text-[#666]">
                <div className="mb-2 text-[#444] font-medium">Tips</div>
                {Array.isArray(item.tips) && item.tips.length > 0 ? (
                  <ul className="list-disc pl-5 space-y-1">
                    {item.tips.map((tip: string, idx: number) => (
                      <li key={idx}>{tip}</li>
                    ))}
                  </ul>
                ) : (
                  <div className="text-gray-400">No tips available</div>
                )}
              </div>
            </div>
          </Col>
        );
      })}
    </Row>
  );
}