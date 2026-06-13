const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: false });
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });

  console.log('🔍 打开百度...');
  await page.goto('https://www.baidu.com');

  // 等待页面完全加载
  await page.waitForLoadState('networkidle');

  // 等待搜索框加载（可能被隐藏，改用 attached）
  await page.locator('#kw').waitFor({ state: 'visible', timeout: 10000 }).catch(async () => {
    console.log('⚠️ 搜索框不可见，尝试处理可能的弹窗/遮罩...');
    // 尝试点击关闭按钮或按 ESC
    await page.keyboard.press('Escape');
    await page.waitForTimeout(1000);
  });

  // 确保搜索框可用
  await page.waitForTimeout(500);

  // 输入搜索关键词
  console.log('✏️ 输入搜索词: Claude Code');
  await page.fill('#kw', 'Claude Code');

  // 点击搜索按钮
  console.log('🖱️ 点击搜索按钮...');
  await page.click('#su');

  // 等待搜索结果加载
  await page.waitForSelector('.result', { timeout: 10000 });

  console.log('✅ 搜索完成！页面已打开。');

  // 截个图保存
  await page.screenshot({ path: 'baidu_result.png', fullPage: false });
  console.log('📸 截图已保存到 baidu_result.png');

  // 不要关闭浏览器，让用户看到结果
  // await browser.close();
})();
