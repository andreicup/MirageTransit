const {chromium}=require('playwright');const fs=require('fs');const path=require('path');const {execFileSync}=require('child_process');
(async()=>{
 const configDir=process.argv[2],output=path.resolve(process.argv[3]);if(fs.existsSync(output))throw new Error('Demo already exists');
 const analyst=JSON.parse(fs.readFileSync(path.join(configDir,'analyst.json'))),decoy=JSON.parse(fs.readFileSync(path.join(configDir,'decoy.json')));
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});const context=await browser.newContext({viewport:{width:1280,height:800},recordVideo:{dir:path.dirname(output),size:{width:1280,height:800}}});const page=await context.newPage();
 const started=Date.now();
 async function caption(text){await page.evaluate(text=>{let box=document.getElementById('demo-caption');if(!box){box=document.createElement('div');box.id='demo-caption';document.body.append(box);}Object.assign(box.style,{position:'fixed',bottom:'16px',left:'50%',transform:'translateX(-50%)',background:'#172a29',color:'#b3f4dc',border:'1px solid #529e89',padding:'14px 25px',borderRadius:'10px',font:'14px sans-serif',zIndex:'1000',width:'90%',maxWidth:'1080px',boxShadow:'0 10px 50px #000'});box.textContent=text;},text);}
 async function hold(seconds){await page.waitForTimeout(seconds*1000);}
 try{
  await page.goto('http://127.0.0.1:'+analyst.port);await caption('MirageTransit · A cyber-physical deception lab. The fleet, portal, MQTT and CAN share one deterministic state.');await hold(12);
  await page.fill('#password',analyst.password);await page.click('#login-form button');await page.locator('#workspace').waitFor({state:'visible'});await caption('Private analyst workspace. Only this role can inspect evidence, export runs or stop the simulation.');await hold(16);
  await page.fill('#throttle','700');await page.click('#control button');await page.waitForFunction(()=>document.getElementById('control-result').textContent.includes('Accepted'));await caption('Lab inputs are accepted first, then applied at a simulation tick. Speed changes gradually in the synthetic model.');await hold(22);
  await page.goto('http://127.0.0.1:'+decoy.port);await page.click('#document');await page.locator('#document-result').waitFor({state:'visible'});const document=JSON.parse(await page.locator('#document-result').textContent());await caption('The decoy maintenance document plants a run-specific MQTT credential. Every credential and vehicle is synthetic.');await hold(19);
  // A real protocol client reuses exactly the credential read by this browser session.
  execFileSync(process.env.MT_DEMO_PYTHON,['scripts/demo_mqtt_client.py',configDir,JSON.stringify(document.credentials)],{stdio:'pipe'});
  await page.goto('http://127.0.0.1:'+analyst.port);await page.locator('#workspace').waitFor({state:'visible'});await page.click('[data-tab="evidence"]');await page.waitForFunction(()=>document.querySelectorAll('#graph .link-card').length>0);await caption('Exact token reuse connects the portal session to MQTT. This establishes artifact access; it does not identify a person.');await hold(25);
  await page.click('[data-tab="overview"]');await page.locator('.table-wrap').scrollIntoViewIfNeeded();await caption('The MQTT braking command appears in the ordered event timeline. Retrying its command ID does not apply it twice.');await hold(19);
  await page.click('[data-tab="replay"]');const promise=page.waitForEvent('download');await page.click('#export');const download=await promise;const bundle=path.join(configDir,'video-scenario.json');await download.saveAs(bundle);await caption('Export removes network session identities. The scenario contains declarative inputs and expected per-tick hashes.');await hold(15);
  await page.setInputFiles('#replay-file',bundle);await page.waitForFunction(()=>document.getElementById('replay-result').textContent.includes('"verified": true'));await caption('Replay re-executes commands and checks every tick plus the final checkpoint. Reproducibility is tested, not assumed from the seed.');await hold(18);
  await page.click('[data-tab="overview"]');await page.evaluate(()=>window.scrollTo(0,0));await caption('Bounded local lab: three synthetic vehicles, no real ECU connection, no public exposure. Native vCAN and hardware are separate validation gates.');await hold(18);
  while(Date.now()-started<181000)await hold(Math.min(10,(181000-(Date.now()-started))/1000));
  const video=page.video();await context.close();await video.saveAs(output);console.log(JSON.stringify({video:output,duration_seconds:Math.round((Date.now()-started)/1000)}));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
