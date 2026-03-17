import React from 'react';
import { Bar } from 'react-chartjs-2';
import { Chart as ChartJS, CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend } from 'chart.js';

ChartJS.register(CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend);

const Dashboard: React.FC = () => {
  const data = {
    labels: ['Lab 1', 'Lab 2', 'Lab 3'],
    datasets: [{
      label: 'Scores',
      data: [10, 20, 30],
      backgroundColor: 'rgba(54, 162, 235, 0.5)',
    }],
  };
  return <div style={{ padding: '20px' }}><h1>Dashboard</h1><Bar data={data} /></div>;
};
export default Dashboard;
