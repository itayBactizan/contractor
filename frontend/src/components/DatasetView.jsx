import { useState } from 'react'
import CategorySection from './CategorySection.jsx'

// "Dataset (YOLO)" tab: random contracts by MataraDesc saved as clean training images
export default function DatasetView() {
  const [datasetSize, setDatasetSize] = useState(null)

  return (
    <>
      <p className="subtitle">
        Build a YOLO image dataset: 1024×1024 images at the orthophoto&apos;s full resolution (0.2 m per pixel, so
        one image covers 205 m). Everything outside the contract is black and no lines or numbers are drawn.
        Small contracts appear at their true size; large contracts are split into several images. Images are
        saved to <code>dataset/images</code> with
        their metadata in <code>dataset/meta</code> and <code>dataset/metadata.csv</code>. Contracts already in
        the dataset are never picked again.
      </p>
      {datasetSize !== null && (
        <p className="dataset-size">
          Dataset size: <strong>{datasetSize}</strong> images
        </p>
      )}
      <CategorySection
        layer="contracts"
        title="Contracts"
        kind="contract"
        fields={['MataraDesc']}
        idPrefix="dataset"
        sampleUrl="/api/dataset/sample"
        onResults={(data) => setDatasetSize(data.dataset_size)}
      />
    </>
  )
}
