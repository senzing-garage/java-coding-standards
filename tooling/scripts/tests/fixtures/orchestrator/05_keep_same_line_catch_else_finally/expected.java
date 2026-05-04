public class Foo
{
    public void method()
    {
        try {
            doRisky();
        } catch (Exception e) {
            handle(e);
        } finally {
            cleanup();
        }
        if (cond) {
            doYes();
        } else {
            doNo();
        }
    }
}
